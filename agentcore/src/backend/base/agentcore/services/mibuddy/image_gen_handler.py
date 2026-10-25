"""Image generation handler for orchestrator.

Supports image generation via models registered in the Model Registry:
1. OpenAI DALL-E (provider: openai, model_name contains "dall-e")
2. Azure OpenAI DALL-E (provider: azure, model_name contains "dall-e")
3. Nano Banana / Vertex AI Gemini (provider: google, model_name contains "gemini")

All credentials come from the model registry — no hardcoded keys.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _get_settings():
    from agentcore.services.deps import get_settings_service
    return get_settings_service().settings


# ---------------------------------------------------------------------------
# Image editing support (MiBuddy-parity)
# ---------------------------------------------------------------------------

# Keywords that strongly imply the user wants to EDIT a prior image rather
# than generate a brand-new one. Lifted from MiBuddy's
# `is_image_modification_request` (backend/utils/image_storage.py).
_MODIFICATION_KEYWORDS = {
    "change", "modify", "edit", "make", "turn", "replace", "update",
    "convert", "alter", "adjust", "add", "remove", "delete", "insert",
    "apply", "swap",
}
# Pronouns that usually refer to the previous image when context exists
# ("make IT bigger", "change THAT to blue", etc.)
_PRONOUN_REFS = {"it", "this", "that", "them", "these", "those", "its"}

# How many recent assistant messages in the session to scan when looking
# for the last generated image. Matches MiBuddy (they scan last 6).
_LAST_IMAGE_LOOKBACK_MSGS = 6


def is_image_modification_request(prompt: str, has_previous_image: bool) -> bool:
    """Return True when the prompt looks like an edit of an existing image.

    Matches MiBuddy's heuristic: a modification keyword OR a pronoun
    reference, gated on there actually being a previous image in context.
    Without a previous image we always treat requests as fresh generation.
    """
    if not has_previous_image:
        return False
    words = set(prompt.lower().replace(",", " ").replace(".", " ").split())
    has_modifier = bool(words & _MODIFICATION_KEYWORDS)
    has_pronoun = bool(words & _PRONOUN_REFS)
    return has_modifier or has_pronoun


async def session_has_recent_image(session_id: str) -> bool:
    """Cheap check: does the latest assistant message in the session contain image markdown?

    Lexical-only — does not download bytes. Used by the orchestrator routing
    layer to short-circuit ambiguous edit requests ("replace human with robot")
    into the image_gen path before the stateless intent classifier mis-labels
    them as general_chat.
    """
    import re
    try:
        from sqlmodel import select
        from agentcore.services.deps import session_scope
        from agentcore.services.database.models.orch_conversation.model import OrchConversationTable
    except Exception as e:
        logger.debug(f"[ImageGen] Could not import DB deps for image presence check: {e}")
        return False

    try:
        async with session_scope() as db:
            stmt = (
                select(OrchConversationTable)
                .where(
                    OrchConversationTable.session_id == session_id,
                    OrchConversationTable.sender.in_(("agent", "model")),
                )
                .order_by(OrchConversationTable.timestamp.desc())
                .limit(1)
            )
            row = (await db.exec(stmt)).first()
    except Exception as e:
        logger.debug(f"[ImageGen] session_has_recent_image query failed: {e}")
        return False

    if not row:
        return False
    text = getattr(row, "text", "") or ""
    return bool(re.search(r"!\[[^\]]*\]\([^)]+\)", text))


async def _refine_image_edit_prompt(session_id: str, current_query: str) -> str:
    """Rewrite a terse follow-up edit instruction into a detailed standalone prompt.

    Verbatim port of MiBuddy's `refine_image_prompt`
    (backend/utils/image_storage.py:108) called from the image_generation_node
    (backend/agents/image_generation_agent.py:79). System message is copied
    byte-for-byte from MiBuddy. A bare "replace humans with robots" lacks the
    scene context Gemini needs to apply the modification thoroughly — without
    the prior scene description, the model often replaces only one instance.
    This helper pulls the last 6 session messages, asks an LLM to fold them
    into one detailed image prompt, and returns the rewritten string.

    Returns empty string on failure; caller falls back to the original query.
    Reuses the Azure OpenAI client already configured for intent classification.
    """
    try:
        from sqlmodel import select
        from agentcore.services.deps import session_scope
        from agentcore.services.database.models.orch_conversation.model import OrchConversationTable
    except Exception as e:
        logger.debug(f"[ImageGen] Refine: import failed: {e}")
        return ""

    try:
        async with session_scope() as db:
            stmt = (
                select(OrchConversationTable)
                .where(OrchConversationTable.session_id == session_id)
                .order_by(OrchConversationTable.timestamp.desc())
                .limit(6)
            )
            rows = (await db.exec(stmt)).all()
    except Exception as e:
        logger.debug(f"[ImageGen] Refine: history query failed: {e}")
        return ""

    if not rows:
        return ""

    import re as _re
    history_lines: list[str] = []
    for row in reversed(rows):
        sender = (getattr(row, "sender", "") or "").lower()
        text = getattr(row, "text", "") or ""
        if not text:
            continue
        # Strip image markdown so the LLM sees the textual context, not URLs
        text = _re.sub(r"!\[[^\]]*\]\([^)]+\)", "[image]", text).strip()
        if not text:
            continue
        role = "user" if sender == "user" else "assistant"
        history_lines.append(f"{role}: {text}")

    if not history_lines:
        return ""

    history_text = "\n".join(history_lines)

    # Refinement system message. Adapted from MiBuddy
    # (backend/utils/image_storage.py:134-142) but rewritten so the output is
    # an EDIT-AWARE imperative when the user is modifying a prior image,
    # rather than a fresh-image description. A fresh-image description fights
    # Gemini's edit wrapper (which says "Preserve composition, environment
    # layout, background…") and causes the background to change on simple
    # subject swaps like "replace cat with dog". An imperative like
    # "Replace the cat with a dog. Keep the rest of the scene unchanged."
    # plays nicely with the wrapper for both single-subject swaps AND
    # multi-instance category replacements ("replace humans with robots" →
    # "Replace EVERY human with a humanoid robot").
    system_msg = (
        "You are an expert image prompt engineer. Interpret the user's latest request "
        "in the context of the conversation and output a SINGLE prompt for an image model.\n"
        "\n"
        "CASE A — the user is modifying a previous image (e.g. 'make it black', "
        "'replace X with Y', 'change the background', 'add a hat'):\n"
        "- Output an EDIT INSTRUCTION, not a fresh image description.\n"
        "- Start with an imperative edit verb: 'Replace', 'Change', 'Modify', 'Add', "
        "'Remove', 'Recolor', 'Swap', etc.\n"
        "- If the instruction targets a category that may have multiple instances in the "
        "scene ('humans', 'cars', 'workers', 'trees'), explicitly write 'EVERY' or 'ALL' "
        "and require that no instance of the original be left after the edit.\n"
        "- End with a short reminder to preserve everything else, e.g. 'Keep the rest of "
        "the scene (background, lighting, composition, surrounding objects) unchanged.'\n"
        "- DO NOT redescribe the parts of the scene that should stay the same. The image "
        "model already has the reference image — extra description fights the preservation "
        "directive.\n"
        "- DO NOT invent new background, location, or scene elements that the user did not "
        "ask for.\n"
        "\n"
        "CASE B — the user is asking for a brand-new image (no prior image, or the request "
        "is unrelated to anything earlier):\n"
        "- Output a SINGLE, detailed image generation prompt that fully describes the "
        "subject, setting, style, and lighting.\n"
        "\n"
        "Output ONLY the final prompt text. Do not wrap it in quotes. Do not add prefaces "
        "like 'Here is the prompt:' or markdown formatting."
    )

    try:
        from agentcore.services.deps import get_settings_service
        settings = get_settings_service().settings
        endpoint = settings.mibuddy_endpoint
        api_key = settings.mibuddy_api_key
        api_version = settings.mibuddy_api_version
        model_name = settings.intent_classifier_model_name
        if not (endpoint and api_key and model_name):
            logger.debug("[ImageGen] Refine: Azure OpenAI settings missing, skipping")
            return ""

        from langchain_openai import AzureChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = AzureChatOpenAI(  # type: ignore[call-arg]
            azure_endpoint=endpoint,
            azure_deployment=model_name,
            api_version=api_version,
            api_key=api_key,
            temperature=0.3,
            max_tokens=600,
        )
        result = await llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=history_text),
        ])
        refined = (result.content if hasattr(result, "content") else str(result)) or ""
        refined = refined.strip().strip('"').strip("'").strip()
        if refined:
            logger.info(f"[ImageGen] Refined edit prompt: {refined[:200]!r}")
        return refined
    except Exception as e:
        logger.warning(f"[ImageGen] Refine: LLM call failed: {e}")
        return ""


async def _get_last_generated_image(session_id: str, user_id: str) -> bytes | None:
    """Fetch the most recent AI-generated image from the session as raw bytes.

    Scans the last `_LAST_IMAGE_LOOKBACK_MSGS` assistant messages for image
    markdown (`![...](<url>)`) and downloads the first match it finds
    (messages are ordered newest-first). Handles three URL shapes:
      - raw Azure blob URL (public container)
      - auth-proxied `/api/files/images/...` URL (requires user-id mapping)
      - inline `data:image/png;base64,...` URLs

    Returns image bytes or None if no recoverable image is found. Failures
    are logged and swallowed — the caller falls back to fresh generation.
    """
    import re
    try:
        from sqlmodel import select
        from agentcore.services.deps import session_scope
        from agentcore.services.database.models.orch_conversation.model import OrchConversationTable
    except Exception as e:
        logger.debug(f"[ImageGen] Could not import DB deps for image lookup: {e}")
        return None

    try:
        async with session_scope() as db:
            stmt = (
                select(OrchConversationTable)
                .where(
                    OrchConversationTable.session_id == session_id,
                    # Assistant messages are stored as sender="agent" or "model"
                    # depending on whether they came from an agent deployment
                    # or direct model chat. Match either.
                    OrchConversationTable.sender.in_(("agent", "model")),
                )
                .order_by(OrchConversationTable.timestamp.desc())
                .limit(_LAST_IMAGE_LOOKBACK_MSGS)
            )
            rows = (await db.exec(stmt)).all()
    except Exception as e:
        logger.warning(f"[ImageGen] Query for prior image failed: {e}")
        return None

    img_md_re = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    for row in rows:
        text = getattr(row, "text", "") or ""
        match = img_md_re.search(text)
        if not match:
            continue
        url = match.group(1).strip()
        logger.info(f"[ImageGen] Found prior image URL in msg {row.id}: {url[:80]}...")

        # Case 1: inline base64 data URL
        if url.startswith("data:image/"):
            try:
                import base64
                _, b64 = url.split(",", 1)
                return base64.b64decode(b64)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[ImageGen] Failed to decode inline image: {exc}")
                continue

        # Case 2: auth-proxied URL served by agentcore (/api/files/images/...)
        # URL shapes in the wild:
        #   /api/files/images/{user_id}/{filename}                  ← returned by _save_generated_image
        #     (subfolder implicit = "generated-images")
        #   /api/files/images/{user_id}/generated-images/{filename} ← gallery listing format
        #   /api/orchestrator/images/{user_id}/{subfolder}/{filename}
        # We try the literal path first, then retry with the "generated-images"
        # subfolder inserted (covers the _save_generated_image shape).
        if "/api/files/images/" in url or "/orchestrator/images/" in url:
            from agentcore.services.mibuddy.docqa_storage import get_file_by_path
            parts = url.split("/images/", 1)
            if len(parts) == 2:
                raw_path = parts[1].split("?", 1)[0]  # strip query string
                # Try literal path first (matches gallery URLs that already include subfolder)
                try:
                    return await get_file_by_path(raw_path)
                except Exception as exc1:  # noqa: BLE001
                    logger.debug(f"[ImageGen] Direct path '{raw_path}' failed: {exc1}")
                # Retry with generated-images subfolder injected between user_id
                # and filename (covers _save_generated_image's 2-segment URL).
                path_parts = raw_path.split("/")
                if len(path_parts) == 2:
                    retry_path = f"{path_parts[0]}/generated-images/{path_parts[1]}"
                    try:
                        logger.info(f"[ImageGen] Retrying with generated-images subfolder: {retry_path}")
                        return await get_file_by_path(retry_path)
                    except Exception as exc2:  # noqa: BLE001
                        logger.warning(f"[ImageGen] Retry '{retry_path}' also failed: {exc2}")
                continue

        # Case 3: public/SAS blob URL — fetch over HTTP
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.content
                logger.debug(f"[ImageGen] GET {url[:60]}... → {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ImageGen] HTTP fetch failed: {exc}")
            continue

    return None


# ---------------------------------------------------------------------------
# Image prompt safety enhancement
# ---------------------------------------------------------------------------

def _apply_safety_to_prompt(prompt: str) -> str:
    """Apply safety rules to an image generation prompt.

    Rules (applied to ALL image providers — DALL-E, Azure DALL-E, Nano Banana):
    1. Replace real person requests with generic versions
    2. Block trademarked logo generation
    """
    try:
        company_name = _get_settings().company_kb_name or None
    except Exception:
        company_name = None

    safety_prefix = (
        "IMPORTANT RULES FOR THIS IMAGE: "
        "If a specific real person, celebrity, or public figure is requested, "
        "REPLACE them with a generic, non-identifiable person in the same role. "
        "If a specific company logo or trademarked brand is requested, "
        "create a generic inspired design instead."
    )

    if company_name:
        safety_prefix += (
            f" If {company_name} logo or branding is requested, "
            f"do NOT generate it — official logos must come from brand guidelines."
        )

    return f"{safety_prefix}\n\n{prompt}"


# ---------------------------------------------------------------------------
# Save generated image to storage + DB (for My Images gallery)
# ---------------------------------------------------------------------------

async def _save_generated_image(
    image_bytes: bytes,
    user_id: str,
    ext: str = "png",
    prompt: str = "",
) -> str:
    """Save a generated image to storage and create a File DB record.

    Returns the authenticated proxy URL: /api/files/images/{user_id}/{file_name}
    The frontend loads this URL with JWT auth, so it works regardless of
    whether the blob container is public or private.

    For external sharing, callers should separately resolve the public blob
    URL via get_public_blob_url(file_path) when the container has public
    access configured.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from agentcore.services.deps import session_scope
    from agentcore.services.database.models.file.model import File as UserFile
    from agentcore.services.mibuddy.docqa_storage import (
        save_file as mibuddy_save,
        FileCategory,
    )

    # Generate filename
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    file_name = f"{ts}_ai_generated_{uuid4().hex[:6]}.{ext}"

    # Save to dedicated MiBuddy container → {user_id}/generated-images/{file_name}
    file_path = await mibuddy_save(user_id, file_name, image_bytes, category=FileCategory.GENERATED_IMAGES)
    file_size = len(image_bytes)

    # Create DB record so it appears in My Images gallery
    display_name = file_name
    try:
        async with session_scope() as db:
            new_file = UserFile(
                id=uuid4(),
                user_id=user_id,
                name=display_name,
                path=file_path,
                size=file_size,
            )
            db.add(new_file)
            await db.commit()
        logger.info(f"[ImageGen] Saved image to gallery: {file_path}")
    except Exception as e:
        logger.warning(f"[ImageGen] Failed to save image to DB: {e}")

    return f"/api/files/images/{user_id}/{file_name}"


async def _download_and_save_image(
    image_url: str,
    user_id: str,
    prompt: str = "",
) -> str | None:
    """Download image from URL and save to storage.

    Returns local serving URL or None if download fails.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            image_bytes = resp.content

        # Detect extension from content type
        content_type = resp.headers.get("content-type", "image/png")
        ext = content_type.split("/")[-1].split(";")[0]
        if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
            ext = "png"

        return await _save_generated_image(image_bytes, user_id, ext, prompt)
    except Exception as e:
        logger.warning(f"[ImageGen] Failed to download/save image: {e}")
        return None


async def _save_image_from_result(result: dict, user_id: str, prompt: str) -> dict:
    """Extract image from result, save to storage, replace URL with local serving URL.

    Handles both:
    - DALL-E results: ![Generated Image](https://oaidalleapi...)  → download + save
    - Nano Banana results: ![...](data:image/png;base64,...)  → decode + save
    """
    import re

    response_text = result.get("response_text", "")

    # Find markdown image: ![alt](url)
    match = re.search(r'!\[([^\]]*)\]\(([^)]+)\)', response_text)
    if not match:
        return result

    alt_text = match.group(1)
    image_src = match.group(2)

    try:
        if image_src.startswith("data:image/"):
            # Base64 inline image (Nano Banana)
            # Format: data:image/png;base64,iVBOR...
            header, b64_data = image_src.split(",", 1)
            ext = header.split("/")[1].split(";")[0]
            image_bytes = base64.b64decode(b64_data)
            local_url = await _save_generated_image(image_bytes, user_id, ext, prompt)
        elif image_src.startswith("http"):
            # Remote URL (DALL-E)
            local_url = await _download_and_save_image(image_src, user_id, prompt)
        else:
            return result

        if local_url:
            # Replace the URL in response text with local serving URL
            new_response = response_text.replace(image_src, local_url)
            result["response_text"] = new_response
            result["image_path"] = local_url

    except Exception as e:
        logger.warning(f"[ImageGen] Failed to save image from result: {e}")

    return result


# ---------------------------------------------------------------------------
# Fetch model config from registry
# ---------------------------------------------------------------------------

def _is_image_capable(config: dict) -> bool:
    """Check if a model config indicates image generation capability."""
    from agentcore.services.mibuddy.model_capabilities import detect_capabilities
    caps = detect_capabilities(
        config.get("provider", ""),
        config.get("model_name", ""),
        config.get("capabilities"),
    )
    return bool(caps.get("image_generation"))


async def _fetch_model_config(model_id: str) -> dict:
    """Fetch decrypted config for a model from the model service."""
    from agentcore.services.deps import get_settings_service
    settings = get_settings_service().settings

    headers = {"x-api-key": settings.model_service_api_key} if settings.model_service_api_key else {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{settings.model_service_url}/v1/registry/models/{model_id}/config",
            headers=headers,
        )
        if resp.status_code == 404:
            raise ValueError(f"Model {model_id} not found in registry.")
        resp.raise_for_status()
        return resp.json()


async def _get_image_model_config(model_id: str | None = None) -> dict:
    """Fetch the decrypted config for an image-capable model.

    Priority:
    1. User's selected model (if it has image capability)
    2. IMAGE_GEN_MODEL_ID from settings
    3. Auto-discover from registry (find dall-e/gemini model)

    If the user selected a non-image model (e.g. gpt-5.1), it is skipped
    and the system finds a proper image model instead.
    """
    from agentcore.services.deps import get_settings_service
    settings = get_settings_service().settings

    # Step 1: Check user's selected model
    if model_id:
        try:
            config = await _fetch_model_config(model_id)
            if _is_image_capable(config):
                logger.info(f"Using user-selected image model: {config.get('model_name')}")
                return config
            else:
                logger.info(
                    f"User-selected model '{config.get('model_name')}' is not image-capable, "
                    "finding an image model instead."
                )
        except Exception as e:
            logger.warning(f"Failed to fetch user-selected model {model_id}: {e}")

    # Step 2: Check IMAGE_GEN_MODEL_ID setting
    if settings.image_gen_model_id:
        try:
            config = await _fetch_model_config(settings.image_gen_model_id)
            if _is_image_capable(config):
                logger.info(f"Using default image model from settings: {config.get('model_name')}")
                return config
        except Exception as e:
            logger.warning(f"Failed to fetch default image model: {e}")

    # Step 3: Auto-discover
    discovered_id = await _auto_discover_image_model()
    if discovered_id:
        config = await _fetch_model_config(discovered_id)
        logger.info(f"Auto-discovered image model: {config.get('model_name')}")
        return config

    raise ValueError(
        "No image generation model available. "
        "Register a DALL-E or Gemini model in the Model Registry, "
        "or set capabilities.image_generation=true on a model."
    )


async def _auto_discover_image_model() -> str | None:
    """Find the first image-capable model in the registry.

    Looks for models with:
    - model_name containing 'dall-e', 'dalle', or 'gemini' + 'image'
    - OR capabilities.image_generation == true
    """
    from agentcore.services.model_service_client import fetch_registry_models_async

    try:
        all_models = await fetch_registry_models_async(active_only=True)
        for m in all_models:
            name = (m.get("model_name") or "").lower()
            display = (m.get("display_name") or "").lower()
            caps = m.get("capabilities") or {}

            if caps.get("image_generation"):
                return str(m["id"])
            if any(kw in name or kw in display for kw in ("dall-e", "dalle", "image-gen", "gemini-image")):
                return str(m["id"])
    except Exception as e:
        logger.warning(f"Auto-discover image model failed: {e}")

    return None


# ---------------------------------------------------------------------------
# DALL-E (OpenAI native)
# ---------------------------------------------------------------------------

async def _generate_dalle_openai(prompt: str, config: dict) -> dict:
    """Generate image via OpenAI DALL-E API using registry config."""
    prompt = _apply_safety_to_prompt(prompt)
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "") or "https://api.openai.com"
    model_name = config.get("model_name", "dall-e-3")

    url = f"{base_url.rstrip('/')}/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1,
        "response_format": "url",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    image_url = ""
    revised_prompt = ""
    if data.get("data") and len(data["data"]) > 0:
        image_url = data["data"][0].get("url", "")
        revised_prompt = data["data"][0].get("revised_prompt", "")

    if image_url:
        text = f"![Generated Image]({image_url})"
        return {"response_text": text, "model_name": model_name}

    return {"response_text": "Image generation completed but no image was returned.", "model_name": model_name}


# ---------------------------------------------------------------------------
# DALL-E (Azure OpenAI)
# ---------------------------------------------------------------------------

async def _generate_dalle_azure(prompt: str, config: dict) -> dict:
    """Generate image via Azure OpenAI DALL-E using the OpenAI Python SDK
    (matches MiBuddy's exact approach). Returns base64 decoded and uses b64_json
    response format like MiBuddy.
    """
    import asyncio
    import base64
    from openai import AzureOpenAI

    prompt = _apply_safety_to_prompt(prompt)
    api_key = config.get("api_key", "")
    provider_config = config.get("provider_config", {})
    endpoint = config.get("base_url", "") or provider_config.get("azure_endpoint", "")
    deployment = provider_config.get("azure_deployment", config.get("model_name", "dall-e-3"))
    api_version = provider_config.get("api_version", "2024-12-01-preview")

    if not endpoint:
        raise ValueError("Azure DALL-E model missing base_url / azure_endpoint in registry.")

    logger.info(f"[DALL-E Azure] endpoint={endpoint}, deployment={deployment}, api_version={api_version}")

    def _call_sdk():
        client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
            timeout=60.0,
        )
        return client.images.generate(
            model=deployment,
            prompt=prompt,
            size="1024x1024",
            response_format="b64_json",
        )

    try:
        result = await asyncio.to_thread(_call_sdk)

        # Prefer base64 (what MiBuddy uses)
        b64 = getattr(result.data[0], "b64_json", None)
        if b64:
            # Build data URL so frontend can render directly
            data_url = f"data:image/png;base64,{b64}"
            return {"response_text": f"![Generated Image]({data_url})", "model_name": deployment}

        # Fallback: URL response
        url_out = getattr(result.data[0], "url", None)
        if url_out:
            return {"response_text": f"![Generated Image]({url_out})", "model_name": deployment}

        return {"response_text": "Image generation completed but no image was returned.", "model_name": deployment}
    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"[DALL-E Azure] Failed: {type(e).__name__}: {e}")
        # Graceful messages per error type (matches MiBuddy's user-friendly fallbacks)
        if "deprecated" in error_str or "410" in error_str:
            msg = "This image model is no longer available. Please use Nano Banana or contact your admin."
        elif "safety" in error_str or "unsafe" in error_str or "content_policy" in error_str:
            msg = "Image could not be generated due to content safety filters. Try a different prompt."
        elif "timeout" in error_str or "503" in error_str or "service unavailable" in error_str:
            msg = "Image service is temporarily unavailable. Please try again in a moment."
        elif "bad request" in error_str or "invalid" in error_str:
            msg = "Unable to generate this image. Please rephrase your prompt."
        else:
            msg = f"Image generation failed: {e}"
        return {"response_text": msg, "model_name": deployment}


# ---------------------------------------------------------------------------
# Nano Banana (Google Vertex AI Gemini image generation)
# ---------------------------------------------------------------------------

async def _generate_nano_banana(
    prompt: str,
    config: dict,
    reference_image_bytes: bytes | None = None,
) -> dict:
    """Generate or EDIT an image via Google Vertex AI Gemini.

    When `reference_image_bytes` is provided, the call becomes an edit:
    the image is attached as `inlineData` on the request, and the prompt
    switches to a preservation-focused template that instructs the model
    to apply only the requested change while keeping the rest of the
    scene intact (matches MiBuddy's behaviour in
    `backend/utils/model.py::generate_image_nanobanana`).

    Registry model should have:
    - provider: "google" / "google_vertex" / "google_genai_vertex"
    - api_key: service account JSON content or path
    - provider_config.project_id: GCP project ID
    - provider_config.location: region (default: us-central1)
    - model_name: e.g. "gemini-2.5-flash-image"
    """
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    import json
    import tempfile

    provider_config = config.get("provider_config", {})
    project_id = provider_config.get("project_id", "")
    location = provider_config.get("location", "us-central1")
    model_name = config.get("model_name", "gemini-2.5-flash-image")
    api_key_or_path = config.get("api_key", "")

    if not project_id:
        raise ValueError("Nano Banana model missing provider_config.project_id in registry.")

    # Resolve service account credentials
    sa_path = api_key_or_path
    temp_file = None

    # If api_key is JSON content (not a path), write to temp file
    if api_key_or_path.strip().startswith("{"):
        try:
            sa_data = json.loads(api_key_or_path)
            temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump(sa_data, temp_file)
            temp_file.close()
            sa_path = temp_file.name
        except json.JSONDecodeError:
            pass

    if not sa_path or not os.path.exists(sa_path):
        raise ValueError(
            f"Nano Banana service account not found: {sa_path}. "
            "Set api_key to the SA JSON file path or inline JSON content in the registry."
        )

    try:
        credentials = service_account.Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        authed_session = AuthorizedSession(credentials)

        vertex_model = f"projects/{project_id}/locations/{location}/publishers/google/models/{model_name}"
        endpoint = f"https://{location}-aiplatform.googleapis.com/v1/{vertex_model}:generateContent"

        # Branch the prompt + request body depending on whether we're editing
        # a prior image or generating one from scratch.
        # Edit prompt + parts ordering match MiBuddy's working implementation
        # in backend/utils/model.py::generate_image_nanobanana — the reference
        # image is sent FIRST as the primary visual ground truth, then the
        # text instruction. The preservation list explicitly omits "subjects"
        # because the whole point of an edit like "replace humans with robots"
        # is to change the subjects; instructing the model to preserve them
        # makes Gemini leave the original people in the scene. The full
        # `_apply_safety_to_prompt` preamble is also skipped here because its
        # "REPLACE real people with a generic person" rule collides with
        # replace/swap edits — instead we use MiBuddy's single-sentence guard.
        parts: list[dict] = []
        if reference_image_bytes:
            import base64 as _b64
            ref_b64 = _b64.b64encode(reference_image_bytes).decode("utf-8")
            enhanced_prompt = (
                "Edit the provided reference image using it as the base.\n"
                "- Preserve the camera angle, composition, framing, environment, background, "
                "machinery, signage, lighting, and overall scene identity.\n"
                f"- Apply this requested modification: {prompt}.\n"
                "- If the modification names a category that has multiple instances in the "
                "image (e.g. 'humans', 'workers', 'cars', 'trees'), you MUST update EVERY "
                "single occurrence of that category. After the edit, NO original instance "
                "of the modified category should remain anywhere in the image.\n"
                "- The preservation directive above does NOT apply to the specific subjects "
                "or objects being modified — those are precisely what the user wants changed.\n"
                "- You may adjust lighting, reflections, shading, and color interactions ONLY "
                "if required for realism.\n"
                "- Do NOT redesign the scene or alter elements unrelated to the requested change.\n"
                "If a real person or celebrity is requested, replace with a generic "
                "non-identifiable person."
            )
            # Reference image FIRST (primary ground truth), prompt LAST
            parts.append({"inlineData": {"mimeType": "image/png", "data": ref_b64}})
            parts.append({"text": enhanced_prompt})
            logger.info(f"[ImageGen] Editing reference image ({len(reference_image_bytes)} bytes)")
            logger.info(f"[ImageGen] Full edit prompt sent to Gemini:\n{enhanced_prompt}")
        else:
            safe_prompt = _apply_safety_to_prompt(prompt)
            enhanced_prompt = f"Generate a high-quality image of: {safe_prompt}"
            parts.append({"text": enhanced_prompt})

        body = {"contents": [{"role": "user", "parts": parts}]}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(authed_session.post, endpoint, json=body, timeout=30)

                if not response.ok:
                    if response.status_code in [429, 500, 503]:
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    error_text = response.text[:200]
                    logger.error(f"Nano Banana attempt {attempt + 1} failed: {response.status_code} - {error_text}")
                    return {"response_text": f"Image generation failed: {error_text}", "model_name": "nano-banana"}

                data = response.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])

                # Check for safety block
                finish_reason = data.get("candidates", [{}])[0].get("finishReason", "")
                if finish_reason == "IMAGE_SAFETY":
                    return {"response_text": "Image was blocked due to safety filters.", "model_name": "nano-banana"}

                text_parts = [p.get("text", "") for p in parts if "text" in p]
                text = " ".join(text_parts).strip() or "Here is your generated image."

                inline_b64 = next((p["inlineData"]["data"] for p in parts if "inlineData" in p), None)
                if inline_b64:
                    response_text = f"{text}\n\n![Generated Image](data:image/png;base64,{inline_b64})"
                    return {"response_text": response_text, "model_name": "nano-banana"}
                else:
                    return {"response_text": text, "model_name": "nano-banana"}

            except Exception as e:
                logger.error(f"Nano Banana attempt {attempt + 1} error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                return {"response_text": f"Image generation failed: {str(e)}", "model_name": "nano-banana"}

        return {"response_text": "Image generation failed after retries.", "model_name": "nano-banana"}

    finally:
        if temp_file:
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main handler — routes based on registry model config
# ---------------------------------------------------------------------------

async def _find_image_model_by_name() -> dict | None:
    """Find image model in registry by display name (IMAGE_GEN_MODEL_NAME) or auto-discover."""
    settings = _get_settings()
    model_name_setting = settings.image_gen_model_name

    from agentcore.services.model_service_client import fetch_registry_models_async

    try:
        all_models = await fetch_registry_models_async(active_only=True)
    except Exception as e:
        logger.warning(f"[ImageGen] Failed to fetch registry models: {e}")
        return None

    # Search by display name or model name
    if model_name_setting:
        name_lower = model_name_setting.lower()
        for m in all_models:
            display = (m.get("display_name") or "").lower()
            model_n = (m.get("model_name") or "").lower()
            if name_lower == display or name_lower == model_n or name_lower in display:
                logger.info(f"[ImageGen] Found model by name '{model_name_setting}': id={m.get('id')}")
                return m

    # Auto-discover: find first image-capable model
    for m in all_models:
        name = (m.get("model_name") or "").lower()
        display = (m.get("display_name") or "").lower()
        caps = m.get("capabilities") or {}
        if caps.get("image_generation"):
            return m
        if any(kw in name or kw in display for kw in ("dall-e", "dalle", "nano-banana", "gemini-image", "flash-image")):
            return m

    return None


async def handle_image_generation(
    query: str,
    model_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Generate or EDIT an image using a model from the registry.

    When `session_id` is provided, the handler checks the session's recent
    assistant messages for a previously generated image. If the user's
    prompt looks like an edit request (keywords: change / modify / add /
    remove / etc., or pronoun references like "it") AND a prior image
    exists, Nano Banana is called in image-to-image mode with the prior
    image as a reference. Otherwise the call is a fresh generation.

    Finds the image model by:
    1. IMAGE_GEN_MODEL_NAME setting (display name match in registry)
    2. Auto-discover (first model with image_generation capability)

    Returns dict with keys: response_text, model_name
    """
    try:
        # Rate limiting
        if user_id:
            from agentcore.services.mibuddy.rate_limiter import get_image_rate_limiter
            limiter = get_image_rate_limiter()
            allowed, reset_in = limiter.check(user_id)
            if not allowed:
                minutes = round((reset_in or 0) / 60, 1)
                return {
                    "response_text": f"You have exceeded the image generation limit. Please try again in {minutes} minutes.",
                    "model_name": "rate-limited",
                }

        # Find image model from registry
        registry_model = await _find_image_model_by_name()
        if not registry_model:
            return {
                "response_text": "No image generation model found in registry. Register a DALL-E or Nano Banana model.",
                "model_name": "not-configured",
            }

        model_registry_id = str(registry_model.get("id", ""))
        logger.info(f"[ImageGen] Using registry model: {registry_model.get('display_name')} (id={model_registry_id})")

        # Fetch decrypted config from model service
        config = await _fetch_model_config(model_registry_id)
        provider = (config.get("provider") or "").lower()
        model_name = (config.get("model_name") or "").lower()

        logger.info(f"[ImageGen] Provider={provider}, model={model_name}")

        # --- Image-edit detection: look up the last generated image in this
        # session so we can pass it to Nano Banana as a reference when the
        # user's prompt implies a modification. Only Nano Banana (Vertex AI
        # Gemini) supports this today — DALL-E / Azure DALL-E use a
        # different "edits" API that isn't wired up here.
        reference_image_bytes: bytes | None = None
        is_edit = False
        # MiBuddy parity (image_generation_agent.py:78-84): refinement runs
        # whenever there's prior session history, regardless of which model
        # backend will run. The refined prompt then goes to BOTH Nano Banana
        # and DALL-E. Our refinement system_msg has been tuned to emit an
        # edit-aware imperative (not a fresh-image description) so the
        # resulting prompt does not fight the preservation wrapper used by
        # the Nano Banana edit branch.
        prompt_for_model = query
        if session_id and user_id:
            prior_bytes = await _get_last_generated_image(session_id, user_id)
            if prior_bytes and is_image_modification_request(query, True):
                reference_image_bytes = prior_bytes
                is_edit = True
                logger.info(
                    f"[ImageGen] Detected edit request for {len(prior_bytes)} byte prior image"
                )
            refined = await _refine_image_edit_prompt(session_id, query)
            if refined:
                prompt_for_model = refined

        # Route to correct backend
        if provider in ("google", "google_vertex", "google_genai_vertex") or "gemini" in model_name:
            result = await _generate_nano_banana(prompt_for_model, config, reference_image_bytes=reference_image_bytes)
        elif provider == "azure" and "dall" in model_name:
            if is_edit:
                logger.info("[ImageGen] Edit requested but DALL-E edits API not wired — doing fresh generation with refined prompt")
            result = await _generate_dalle_azure(prompt_for_model, config)
        elif provider == "openai" and "dall" in model_name:
            if is_edit:
                logger.info("[ImageGen] Edit requested but DALL-E edits API not wired — doing fresh generation with refined prompt")
            result = await _generate_dalle_openai(prompt_for_model, config)
        elif provider in ("openai", "azure"):
            result = await _generate_dalle_openai(prompt_for_model, config) if provider == "openai" else await _generate_dalle_azure(prompt_for_model, config)
        else:
            result = {"response_text": f"Unsupported image model provider: {provider}", "model_name": "unknown"}

        # Record successful generation for rate limiting
        if user_id and result.get("response_text") and "failed" not in result.get("response_text", "").lower():
            from agentcore.services.mibuddy.rate_limiter import get_image_rate_limiter
            get_image_rate_limiter().record(user_id)

        # Save generated image to storage + DB for My Images gallery
        if user_id and result.get("response_text"):
            result = await _save_image_from_result(result, user_id, query)

        return result

    except Exception as e:
        logger.error(f"[ImageGen] Failed: {e}")
        return {"response_text": "Image generation encountered an error. Please try again.", "model_name": "image-generation"}


async def _generate_via_chat_model(query: str, config: dict) -> dict:
    """Fallback: call registry model as a chat model (for models with built-in image gen)."""
    from agentcore.services.deps import get_settings_service
    from agentcore.services.model_service_client import MicroserviceChatModel
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = get_settings_service().settings
    model_id = settings.image_gen_model_id

    model = MicroserviceChatModel(
        service_url=settings.model_service_url,
        service_api_key=settings.model_service_api_key,
        registry_model_id=model_id,
        provider="openai",
        model=f"image-gen-{model_id[:8]}",
    )

    result = await model.ainvoke([
        SystemMessage(content="You are an image generation assistant. Generate images as requested."),
        HumanMessage(content=query),
    ])
    response_text = result.content if hasattr(result, "content") else str(result)
    metadata = getattr(result, "response_metadata", {}) or {}
    return {"response_text": response_text, "model_name": metadata.get("model_name", "image-generation")}


async def handle_image_generation_stream(
    query: str,
    model_id: str | None = None,
    user_id: str | None = None,
    event_manager=None,
    session_id: str | None = None,
) -> dict:
    """Image generation with progress events (not truly streaming)."""
    if event_manager:
        event_manager.on_token(data={"chunk": "Generating image... "})

    result = await handle_image_generation(
        query,
        model_id=model_id,
        user_id=user_id,
        session_id=session_id,
    )

    if event_manager:
        event_manager.on_token(data={"chunk": result["response_text"]})

    return result
