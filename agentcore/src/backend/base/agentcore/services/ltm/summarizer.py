"""LTM Conversation Summarizer.

Uses an LLM (from settings config or passed directly) to summarize
conversation history into concise paragraphs for long-term storage.
"""

from __future__ import annotations

from loguru import logger

from agentcore.schema.message import Message

SUMMARIZATION_PROMPT = """\
You are a conversation summarizer. Summarize the following conversation between \
a user and an AI assistant into a concise paragraph. Capture the key topics discussed, \
questions asked, decisions made, important context, and any facts or preferences revealed. \
Keep the summary under {max_tokens} tokens.

Conversation:
{conversation_text}

Concise Summary:"""


_cached_agent_llm: dict | None = None  # {agent_id: {registry_id, provider, model}}


def _get_llm_from_agent_flow(agent_id: str) -> dict | None:
    """Extract the LLM component's registry_model_id, provider, and model
    from the agent's flow data (same LLM the user selected in the canvas).
    """
    global _cached_agent_llm
    # No cache — always read fresh from DB so model changes are picked up immediately

    try:
        import json
        import re as _re

        # Build a sync psycopg2 connection from DB settings
        # (async engine can't be used in sync context)
        from agentcore.services.deps import get_settings_service
        _settings = get_settings_service().settings
        db_url = str(_settings.database_url or "")
        # Normalize to plain postgresql:// for psycopg2
        db_url = _re.sub(r"^postgresql\+\w+://", "postgresql://", db_url)

        import psycopg2
        conn = psycopg2.connect(db_url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT data FROM agent WHERE id = %s", (agent_id,))
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()

        if not row or not row[0]:
            return None

        agent_data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        nodes = agent_data.get("nodes", [])

        for node in nodes:
            data = node.get("data", {})
            node_type = data.get("type", "")
            if node_type != "RegistryModelComponent":
                continue

            template = data.get("node", {}).get("template", {})

            # Extract registry_model: "display_name | model_name | uuid"
            reg_field = template.get("registry_model", {})
            raw_value = reg_field.get("value", "") if isinstance(reg_field, dict) else str(reg_field)

            if not raw_value or "|" not in str(raw_value):
                continue

            parts = [p.strip() for p in str(raw_value).split("|")]
            if len(parts) >= 3:
                # Get provider from template
                provider_field = template.get("provider", {})
                provider = provider_field.get("value", "") if isinstance(provider_field, dict) else str(provider_field)

                # Normalize provider to lowercase (same as RegistryModelComponent.build_model)
                PROVIDER_LABEL_TO_KEY = {
                    "OpenAI": "openai", "Azure": "azure", "Anthropic": "anthropic",
                    "Google": "google", "Groq": "groq", "Custom Model": "openai_compatible",
                }
                raw_provider = provider or parts[0]
                normalized_provider = PROVIDER_LABEL_TO_KEY.get(raw_provider, raw_provider).lower()

                result_dict = {
                    "agent_id": agent_id,
                    "registry_id": parts[2],
                    "provider": normalized_provider,
                    "model": parts[1],
                }
                _cached_agent_llm = result_dict
                logger.info(f"[LTM] Found LLM in agent flow: provider={result_dict['provider']}, "
                            f"model={result_dict['model']}, registry_id={result_dict['registry_id']}")
                return result_dict

    except Exception as e:
        logger.warning(f"[LTM] Could not extract LLM from agent flow: {e}")

    return None


def _get_ltm_llm(agent_id: str | None = None):
    """Build a MicroserviceChatModel using the LLM selected in the agent's flow.

    Priority:
    1. LLM from agent's canvas flow (same model user selected)
    2. LTM_LLM_REGISTRY_MODEL_ID from settings (explicit override)
    3. Auto-discover from Model Registry DB
    """
    from agentcore.services.deps import get_settings_service
    from agentcore.services.model_service_client import MicroserviceChatModel, _get_model_service_settings

    settings = get_settings_service().settings
    service_url, service_api_key = _get_model_service_settings()

    registry_id = None
    provider = ""
    model = ""

    # 1. Try to get LLM from agent's flow (highest priority)
    if agent_id:
        flow_llm = _get_llm_from_agent_flow(agent_id)
        if flow_llm:
            registry_id = flow_llm["registry_id"]
            provider = flow_llm["provider"]
            model = flow_llm["model"]

    # 2. Fallback to explicit settings
    if not registry_id:
        registry_id = settings.ltm_llm_registry_model_id

    # 3. Auto-discover from Model Registry
    if not registry_id:
        try:
            from agentcore.services.model_service_client import fetch_registry_models

            # First try filtering by provider
            models = fetch_registry_models(
                provider=settings.ltm_llm_provider,
                model_type="llm",
                active_only=True,
            )
            logger.info(f"[LTM] Registry lookup: provider={settings.ltm_llm_provider}, found {len(models)} models")

            # If no results with provider filter, try all models
            if not models:
                models = fetch_registry_models(model_type="llm", active_only=True)
                logger.info(f"[LTM] Registry lookup (all providers): found {len(models)} models")

            # Find matching model by name
            for m in models:
                model_name = m.get("model_name", "") or m.get("name", "")
                if settings.ltm_llm_model and model_name == settings.ltm_llm_model:
                    registry_id = str(m.get("id", ""))
                    _cached_registry_model_id = registry_id
                    _discovered_provider = m.get("provider", "")
                    _discovered_model = model_name
                    logger.info(f"[LTM] Auto-discovered registry_model_id={registry_id} for {model_name} ({_discovered_provider})")
                    break

            # If no exact match, try partial match
            if not registry_id:
                for m in models:
                    model_name = m.get("model_name", "") or m.get("name", "")
                    if settings.ltm_llm_model and settings.ltm_llm_model in model_name:
                        registry_id = str(m.get("id", ""))
                        _cached_registry_model_id = registry_id
                        _discovered_provider = m.get("provider", "")
                        _discovered_model = model_name
                        logger.info(f"[LTM] Partial match: registry_model_id={registry_id} for {model_name} ({_discovered_provider})")
                        break

            # Last resort — use first available model
            if not registry_id and models:
                registry_id = str(models[0].get("id", ""))
                _cached_registry_model_id = registry_id
                _discovered_provider = models[0].get("provider", "")
                _discovered_model = models[0].get("model_name", "") or models[0].get("name", "")
                logger.info(f"[LTM] Using first available: {_discovered_model} ({_discovered_provider}) (id={registry_id})")

            # Fallback: query the DB directly to get id, provider, and model_name
            if not registry_id:
                try:
                    from agentcore.services.deps import get_db_service
                    from sqlalchemy import text as sa_text

                    db_service = get_db_service()
                    with db_service.engine.connect() as conn:
                        if settings.ltm_llm_provider:
                            result = conn.execute(sa_text(
                                "SELECT id, model_name, provider FROM model_registry "
                                "WHERE is_active = true AND model_type = 'llm' "
                                "AND provider = :provider ORDER BY created_at DESC LIMIT 5"
                            ), {"provider": settings.ltm_llm_provider})
                        else:
                            result = conn.execute(sa_text(
                                "SELECT id, model_name, provider FROM model_registry "
                                "WHERE is_active = true AND model_type = 'llm' "
                                "ORDER BY created_at DESC LIMIT 5"
                            ))
                        rows = result.fetchall()
                        logger.info(f"[LTM] DB lookup found {len(rows)} LLM models")
                        for row in rows:
                            if settings.ltm_llm_model and settings.ltm_llm_model in (row[1] or ""):
                                registry_id = str(row[0])
                                _discovered_provider = row[2]
                                _discovered_model = row[1]
                                _cached_registry_model_id = registry_id
                                logger.info(f"[LTM] DB match: registry_model_id={registry_id} for {row[1]} ({row[2]})")
                                break
                        if not registry_id and rows:
                            registry_id = str(rows[0][0])
                            _discovered_provider = rows[0][2]
                            _discovered_model = rows[0][1]
                            _cached_registry_model_id = registry_id
                            logger.info(f"[LTM] DB fallback: using {rows[0][1]} ({rows[0][2]}) (id={registry_id})")
                except Exception as db_err:
                    logger.warning(f"[LTM] DB lookup failed: {db_err}")

            if not registry_id:
                logger.warning("[LTM] No models found in registry! Make sure you've registered a model.")
        except Exception as e:
            logger.warning(f"[LTM] Could not auto-discover registry model: {e}")

    if not registry_id:
        logger.error("[LTM] Cannot create LLM — no registry_model_id found. Register a model in Model Registry.")
        raise ValueError("No LLM model found in Model Registry. Please register at least one LLM model.")

    # Use discovered values from flow/DB if not already set
    if not provider:
        provider = settings.ltm_llm_provider or _discovered_provider or ""
    if not model:
        model = settings.ltm_llm_model or _discovered_model or ""

    return MicroserviceChatModel(
        service_url=service_url,
        service_api_key=service_api_key,
        provider=provider,
        model=model,
        registry_model_id=registry_id,
    )


def _format_messages(messages: list[Message]) -> str:
    """Format a list of Message objects into conversation text."""
    lines = []
    for msg in messages:
        sender = msg.sender_name or msg.sender or "Unknown"
        text = msg.text or ""
        lines.append(f"{sender}: {text}")
    return "\n".join(lines)


async def summarize_conversation(messages: list[Message], llm=None, max_tokens: int = 500, agent_id: str | None = None) -> str:
    """Summarize a list of conversation messages.

    Args:
        messages: List of Message objects (both user and AI messages).
        llm: Optional LangChain BaseChatModel. If None, uses LTM settings to create one.
        max_tokens: Target max tokens for the summary.

    Returns:
        A concise summary string.
    """
    if not messages:
        return ""

    if llm is None:
        llm = _get_ltm_llm(agent_id=agent_id)

    conversation_text = _format_messages(messages)
    prompt = SUMMARIZATION_PROMPT.format(conversation_text=conversation_text, max_tokens=max_tokens)

    try:
        # Log model info for debugging
        model_info = getattr(llm, "registry_model_id", "?")
        provider_info = getattr(llm, "provider", "?")
        model_name = getattr(llm, "model", "?")
        logger.info(f"[LTM] Calling LLM: provider={provider_info}, model={model_name}, registry_id={model_info}")
        logger.info(f"[LTM] Prompt length: {len(prompt)} chars ({len(messages)} messages)")

        response = await llm.ainvoke(prompt)
        summary = response.content if hasattr(response, "content") else str(response)
        summary = summary.strip()
        logger.info(f"[LTM] Summarized {len(messages)} messages into {len(summary)} chars")
        logger.info(f"[LTM] === SUMMARY OUTPUT ===\n{summary}\n=== END SUMMARY ===")
        return summary
    except Exception as e:
        logger.error(f"[LTM] Summarization failed: {e}")
        logger.error(f"[LTM] LLM details: provider={getattr(llm, 'provider', '?')}, model={getattr(llm, 'model', '?')}, registry_id={getattr(llm, 'registry_model_id', '?')}")
        raise
