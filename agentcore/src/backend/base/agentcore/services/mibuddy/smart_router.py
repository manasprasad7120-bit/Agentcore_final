"""Smart Router — auto-selects the best model for a query.

When user selects "Smart Router" from the dropdown, this service
analyzes the query and picks the most suitable model from the registry.

Uses the same LLM as the intent classifier (INTENT_CLASSIFIER_MODEL_NAME + LTM API key).
Reads available models dynamically from the model registry.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Hardcoded model hints — exactly the 4 models from MiBuddy's routing_prompt_template.
# Matched against display_name (case-insensitive substring). When a registry model's
# display_name matches a key, the hint is appended to its description in the prompt.
# Other registry models still appear in the list with their auto-detected capabilities.
KNOWN_MODEL_HINTS: dict[str, str] = {
    "gpt-5.4-mini":      "Use for: extremely complex reasoning, math, multi-step logic, long documents, detailed research, RAG analysis, dense or high-stakes queries.",
    "gpt-5.2":           "Use for: web search, news, time-sensitive topics, query routing/classification, coding help, technical queries. Follow-ups to web-related queries should stay on this model.",
    "gpt-5":             "Use for: general chat, creative writing, brainstorming, greetings, definitions, basic logic, small talk and casual context.",
    "claude-sonnet-4-6": "Use for: advanced reasoning and analytical tasks, long-context conversations, document understanding, complex coding explanations, detailed structured analysis.",
}


def _hint_for(display_name: str) -> str | None:
    """Return the hardcoded MiBuddy hint matching this model's display_name, or None."""
    # Normalize spaces/hyphens/underscores so "GPT 5.2", "gpt-5.2", "GPT_5.2" all match
    def _norm(s: str) -> str:
        return (s or "").lower().replace("_", "").replace("-", "").replace(" ", "")
    name_norm = _norm(display_name)
    for key, hint in KNOWN_MODEL_HINTS.items():
        if _norm(key) in name_norm:
            return hint
    return None


async def _get_available_models() -> list[dict]:
    """Get chat models from registry for routing decisions."""
    from agentcore.services.model_service_client import fetch_registry_models_async
    from agentcore.services.mibuddy.model_capabilities import detect_capabilities

    try:
        all_models = await fetch_registry_models_async(model_type="llm", active_only=True)
    except Exception:
        return []

    models = []
    for m in all_models:
        approval = str(m.get("approval_status", "approved")).lower()
        if approval != "approved":
            continue

        provider = m.get("provider", "")
        model_name = m.get("model_name", "")
        display_name = m.get("display_name", model_name)
        caps = detect_capabilities(provider, model_name, m.get("capabilities"))

        # Skip image-only and web-search-only models
        if caps.get("image_generation") and not caps.get("supports_tool_calling"):
            continue

        models.append({
            "id": str(m.get("id", "")),
            "display_name": display_name,
            "model_name": model_name,
            "provider": provider,
            "reasoning": caps.get("reasoning", False),
            "vision": caps.get("supports_vision", False),
            "tool_calling": caps.get("supports_tool_calling", False),
        })

    return models


def _build_routing_prompt(
    query: str,
    models: list[dict],
    *,
    last_model: str | None = None,
    has_image: bool = False,
    has_document: bool = False,
) -> str:
    """Build the routing prompt with available models.

    Combines:
      - dynamic registry models (with auto-detected capabilities)
      - hardcoded MiBuddy hints for known model names (gpt-5, gpt-5.2, gpt-5.4-mini, claude-sonnet-4-6)
      - follow-up context (last_model)
      - file context (has_image, has_document)
    """
    model_descriptions = []
    for i, m in enumerate(models, 1):
        traits = []
        if m.get("reasoning"):
            traits.append("reasoning/thinking")
        if m.get("vision"):
            traits.append("vision")
        if m.get("tool_calling"):
            traits.append("tool calling")
        traits_str = f" ({', '.join(traits)})" if traits else ""
        line = f"{i}. **{m['display_name']}**{traits_str}"
        # Append MiBuddy-style hint when display_name matches a known model
        hint = _hint_for(m["display_name"])
        if hint:
            line += f"\n   {hint}"
        model_descriptions.append(line)

    models_list = "\n".join(model_descriptions)
    model_names = ", ".join(f'"{m["display_name"]}"' for m in models)

    # Build optional context blocks
    follow_up_block = ""
    if last_model:
        follow_up_block = (
            f"\n### Follow-up Context:\n"
            f"The previous response used: **{last_model}**.\n"
            f"If the current query is a follow-up to a previous web/news/time-sensitive answer, "
            f"keep using the same model. Do NOT downgrade the model for follow-ups.\n"
        )

    file_block = ""
    if has_image:
        file_block += "\n- An IMAGE is attached → prefer a model with vision capability."
    if has_document:
        file_block += "\n- A DOCUMENT is attached → prefer a model with reasoning or long-context support."
    if file_block:
        file_block = f"\n### Attached Files:{file_block}\n"

    return f"""You are an intelligent LLM router that balances accuracy, cost-efficiency, and context awareness.

### Available Models:
{models_list}

### Routing Rules:
- For complex reasoning, math, multi-step logic → pick a model with reasoning capability
- For general chat, greetings, simple questions → pick the fastest/simplest model
- For coding, technical queries → pick a model with tool calling or one of the GPT-5 family
- For web search, news, time-sensitive topics → pick a model with web/search capability
- For image analysis questions → pick a model with vision
- For follow-up questions → keep the same model as the previous answer when context matters
{follow_up_block}{file_block}
### User Query: "{query}"

Respond with ONLY a JSON object: {{"model": "<model display name>"}}
Choose from: {model_names}
Do not include any explanation."""


async def route_to_best_model(
    query: str,
    *,
    last_model: str | None = None,
    has_image: bool = False,
    has_document: bool = False,
) -> tuple[str, str] | None:
    """Analyze query and pick the best model from registry.

    Args:
        query: User's input
        last_model: Display name of model used in previous turn (for follow-up routing)
        has_image: True if user attached an image (prefer vision models)
        has_document: True if user attached a document (prefer reasoning/long-context models)

    Returns (model_id, display_name) or None if routing fails.
    """
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings

    # Get available models
    models = await _get_available_models()
    if not models:
        logger.warning("[SmartRouter] No models available in registry")
        return None

    # Build routing prompt with full context
    prompt = _build_routing_prompt(
        query,
        models,
        last_model=last_model,
        has_image=has_image,
        has_document=has_document,
    )

    # Use same LLM as intent classifier
    # Use smart_router_model_name, fallback to intent_classifier_model_name
    model_name = settings.smart_router_model_name or settings.intent_classifier_model_name
    if not model_name:
        logger.warning("[SmartRouter] No model configured for routing")
        return None

    endpoint = settings.mibuddy_endpoint
    api_key = settings.mibuddy_api_key

    if not endpoint or not api_key:
        logger.warning("[SmartRouter] MIBUDDY_ENDPOINT or MIBUDDY_API_KEY not set")
        return None

    try:
        from langchain_openai import AzureChatOpenAI
        llm = AzureChatOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=model_name,
            api_version=settings.mibuddy_api_version,
            api_key=api_key,
            temperature=1,
            max_tokens=200,
        )

        from langchain_core.messages import HumanMessage, SystemMessage
        result = await llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=query),
        ])

        content = result.content if hasattr(result, "content") else str(result)
        logger.info(f"[SmartRouter] Raw response: {content!r}")

        # Handle empty response — fall back to first model
        if not content or not content.strip():
            logger.warning("[SmartRouter] Empty response from LLM, using first model")
            return models[0]["id"], models[0]["display_name"]

        # Parse response
        json_str = content.strip()
        if "{" in json_str:
            start = json_str.index("{")
            end = json_str.rindex("}") + 1
            json_str = json_str[start:end]
        else:
            # No JSON in response — try to match raw text against model names
            logger.warning(f"[SmartRouter] No JSON in response: {content!r}, trying text match")
            for m in models:
                if m["display_name"].lower() in content.lower():
                    logger.info(f"[SmartRouter] Text match: {m['display_name']} (id={m['id']})")
                    return m["id"], m["display_name"]
            return models[0]["id"], models[0]["display_name"]

        parsed = json.loads(json_str)
        selected_name = parsed.get("model", "")

        # Find matching model
        for m in models:
            if m["display_name"].lower() == selected_name.lower():
                logger.info(f"[SmartRouter] Selected: {m['display_name']} (id={m['id']})")
                return m["id"], m["display_name"]

        # Fuzzy match
        for m in models:
            if selected_name.lower() in m["display_name"].lower() or m["display_name"].lower() in selected_name.lower():
                logger.info(f"[SmartRouter] Fuzzy match: {m['display_name']} (id={m['id']})")
                return m["id"], m["display_name"]

        logger.warning(f"[SmartRouter] Model '{selected_name}' not found in registry, using first model")
        return models[0]["id"], models[0]["display_name"]

    except Exception as e:
        logger.error(f"[SmartRouter] Failed: {e}")
        return None
