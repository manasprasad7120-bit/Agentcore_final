"""Web search handler using Google Gemini with Google Search grounding.

Uses the model from the registry (WEB_SEARCH_MODEL_NAME) for credentials.
Falls back to GEMINI_API_KEY from .env if no registry model found.

When user selects this model from dropdown → normal chat (no search tool)
When intent is web_search → uses GoogleSearch grounding tool
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_settings():
    from agentcore.services.deps import get_settings_service
    return get_settings_service().settings


async def _get_web_search_api_key() -> tuple[str, str]:
    """Get Gemini API key and model name.

    Priority:
    1. From model registry (WEB_SEARCH_MODEL_NAME)
    2. From .env (GEMINI_API_KEY + GEMINI_MODEL)

    Returns (api_key, model_name)
    """
    settings = _get_settings()
    model_name_setting = settings.web_search_model_name

    # Try registry first
    if model_name_setting:
        try:
            from agentcore.services.model_service_client import fetch_registry_models_async

            all_models = await fetch_registry_models_async(active_only=True)
            name_lower = model_name_setting.lower()

            for m in all_models:
                display = (m.get("display_name") or "").lower()
                model_n = (m.get("model_name") or "").lower()
                if name_lower == display or name_lower == model_n or name_lower in display:
                    model_id = str(m.get("id", ""))
                    logger.info(f"[WebSearch] Found registry model: {m.get('display_name')} (id={model_id})")

                    # Fetch decrypted config
                    import httpx
                    url = settings.model_service_url
                    svc_key = settings.model_service_api_key
                    headers = {"x-api-key": svc_key} if svc_key else {}
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.get(f"{url}/v1/registry/models/{model_id}/config", headers=headers)
                        if resp.status_code == 200:
                            config = resp.json()
                            api_key = config.get("api_key", "")
                            model_name = config.get("model_name", "gemini-2.0-flash")
                            if api_key:
                                return api_key, model_name
        except Exception as e:
            logger.warning(f"[WebSearch] Failed to fetch from registry: {e}")

    # Fallback to .env
    api_key = settings.gemini_api_key
    model_name = settings.gemini_model or "gemini-2.0-flash"

    if not api_key:
        raise ValueError("Web search not configured. Register a Gemini model with WEB_SEARCH_MODEL_NAME or set GEMINI_API_KEY.")

    return api_key, model_name


async def handle_web_search(query: str, system_message: str = "") -> dict:
    """Call Gemini with Google Search grounding tool.

    Returns dict with keys: response_text, model_name
    """
    from google import genai
    from google.genai import types

    try:
        api_key, model_name = await _get_web_search_api_key()
        logger.info(f"[WebSearch] Using model={model_name}")

        client = genai.Client(vertexai=True, api_key=api_key)

        contents = [
            types.Content(role="user", parts=[types.Part(text=query)]),
        ]
        if system_message:
            contents.append(
                types.Content(role="user", parts=[types.Part(text=f"SYSTEM INSTRUCTIONS:\n{system_message}")])
            )

        tools = [types.Tool(google_search=types.GoogleSearch())]

        config = types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            max_output_tokens=65535,
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
            ],
            tools=tools,
        )

        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )

        if (
            response.candidates
            and response.candidates[0].content
            and response.candidates[0].content.parts
        ):
            return {"response_text": response.text, "model_name": model_name}
        else:
            return {"response_text": "Unable to retrieve web search results. Please try again.", "model_name": model_name}

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[WebSearch] Failed: {e}")
        return {"response_text": "Web search encountered an error. Please try again.", "model_name": "gemini"}


async def handle_web_search_stream(query: str, system_message: str = "", event_manager=None, enable_reasoning: bool = False) -> dict:
    """Stream web search response.

    When enable_reasoning=True, Gemini 2.5+/3.x emits thought summaries alongside
    the answer via thinking_config.include_thoughts.
    """
    logger.info(f"[WebSearch] handle_web_search_stream CALLED with enable_reasoning={enable_reasoning}, query={query[:50]!r}")
    from google import genai
    from google.genai import types

    try:
        api_key, model_name = await _get_web_search_api_key()
        client = genai.Client(vertexai=True, api_key=api_key)

        contents = [
            types.Content(role="user", parts=[types.Part(text=query)]),
        ]
        if system_message:
            contents.append(
                types.Content(role="user", parts=[types.Part(text=f"SYSTEM INSTRUCTIONS:\n{system_message}")])
            )

        tools = [types.Tool(google_search=types.GoogleSearch())]

        config_kwargs = {
            "temperature": 1,
            "top_p": 0.95,
            "max_output_tokens": 65535,
            "safety_settings": [
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
            ],
            "tools": tools,
        }
        # Enable visible thinking. Gemini 3.x uses thinking_level ("LOW"/"MEDIUM"/"HIGH");
        # Gemini 2.5 uses thinking_budget (int). Try the new API first, then fallback.
        if enable_reasoning:
            # Extract major version from any naming style:
            #   "gemini-3.1-pro-preview", "Gemini 3 Pro", "gemini_3_pro",
            #   "google-3.1", "Gemini 3.2 Ultra" → all detected as major version 3.
            import re as _re
            version_match = _re.search(r"(?:gemini|google)[\s_\-]*(\d+(?:\.\d+)?)", (model_name or "").lower())
            major_version = 0.0
            if version_match:
                try:
                    major_version = float(version_match.group(1))
                except ValueError:
                    major_version = 0.0
            is_gemini_3 = major_version >= 3.0
            logger.info(f"[WebSearch] model_name={model_name!r}, detected version={major_version}, using new API={is_gemini_3}")
            thinking_config = None
            try:
                if is_gemini_3:
                    # Gemini 3.x API
                    thinking_config = types.ThinkingConfig(
                        thinking_level="HIGH",
                        include_thoughts=True,
                    )
                else:
                    # Gemini 2.5 API (thinking_budget=-1 = dynamic)
                    thinking_config = types.ThinkingConfig(
                        thinking_budget=-1,
                        include_thoughts=True,
                    )
                config_kwargs["thinking_config"] = thinking_config
                logger.info(f"[WebSearch] enable_reasoning=True — attached {thinking_config!r}")
            except (AttributeError, TypeError) as e:
                # Fallback: try with only include_thoughts
                try:
                    config_kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
                    logger.info(f"[WebSearch] Fell back to ThinkingConfig(include_thoughts=True): {e}")
                except (AttributeError, TypeError) as e2:
                    logger.warning(f"[WebSearch] ThinkingConfig not supported at all: {e2}")
        else:
            logger.info(f"[WebSearch] enable_reasoning=False — no thinking config")
        config = types.GenerateContentConfig(**config_kwargs)

        full_response = ""
        full_reasoning = ""
        grounding_used = False
        search_queries: list[str] = []
        chunk_count = 0
        answer_chunk_count = 0
        reasoning_chunk_count = 0
        for chunk in client.models.generate_content_stream(
            model=model_name,
            contents=contents,
            config=config,
        ):
            chunk_count += 1
            if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                continue
            # Log grounding metadata (confirms Google Search tool was invoked)
            gm = getattr(chunk.candidates[0], "grounding_metadata", None)
            if gm:
                grounding_used = True
                queries = getattr(gm, "web_search_queries", None) or []
                for q in queries:
                    if q not in search_queries:
                        search_queries.append(q)

            # Split parts into thinking vs answer (Gemini marks thoughts with part.thought=True)
            for part in chunk.candidates[0].content.parts:
                part_text = getattr(part, "text", "") or ""
                if not part_text:
                    continue
                is_thought = getattr(part, "thought", False)
                # Debug once: confirm whether thought flag is being set by Gemini
                if enable_reasoning and not hasattr(handle_web_search_stream, "_logged_first_part"):
                    logger.info(f"[WebSearch][debug] first part: thought={is_thought}, text_len={len(part_text)}, text_preview={part_text[:80]!r}")
                    handle_web_search_stream._logged_first_part = True  # type: ignore[attr-defined]
                if is_thought:
                    reasoning_chunk_count += 1
                    full_reasoning += part_text
                    if event_manager:
                        event_manager.on_token(data={"chunk": part_text, "type": "reasoning"})
                else:
                    answer_chunk_count += 1
                    full_response += part_text
                    if event_manager:
                        event_manager.on_token(data={"chunk": part_text})

        logger.info(f"[WebSearch] Stream stats: total_chunks={chunk_count}, reasoning_parts={reasoning_chunk_count}, answer_parts={answer_chunk_count}")
        if grounding_used:
            logger.info(f"[WebSearch] Google Search tool invoked. Queries: {search_queries}")
        else:
            logger.info("[WebSearch] No grounding metadata — model answered from its knowledge")

        return {
            "response_text": full_response,
            "reasoning_content": full_reasoning or None,
            "model_name": model_name,
        }

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[WebSearch] Stream failed: {e}")
        error_msg = "Web search encountered an error. Please try again."
        if event_manager:
            event_manager.on_token(data={"chunk": error_msg})
        return {"response_text": error_msg, "model_name": "gemini"}
