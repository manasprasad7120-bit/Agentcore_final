"""Direct model chat service for orchestrator.

Calls a registry model directly via MicroserviceChatModel, bypassing agent graphs.
Supports both sync and streaming modes, with CoT reasoning extraction.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agentcore.services.model_service_client import MicroserviceChatModel

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


async def _file_to_base64_url(file_path: str) -> str | None:
    """Convert a file path to a base64 data URL for multimodal LLM input.

    The file_path is a storage-relative path like '{user_id}/chat-images/{filename}'.
    Reads from local disk first, then falls back to Azure Blob Storage (MiBuddy container).
    Returns None if the file can't be read from either location.
    """
    try:
        from agentcore.services.deps import get_settings_service
        settings = get_settings_service()
        config_dir = Path(settings.settings.config_dir)

        file_name = file_path.split("/")[-1]
        mime_type = mimetypes.guess_type(file_name)[0] or "image/png"
        data: bytes | None = None

        # Try 1: Local disk
        actual_path = config_dir / file_path
        if actual_path.exists():
            data = actual_path.read_bytes()
            logger.info(f"[FileToBase64] Read from local: {actual_path}")

        # Try 2: Azure Blob Storage (MiBuddy container)
        if data is None:
            try:
                from agentcore.services.mibuddy.docqa_storage import _get_container
                container = await _get_container()
                if container:
                    blob_client = container.get_blob_client(file_path)
                    download = await blob_client.download_blob()
                    data = await download.readall()
                    logger.info(f"[FileToBase64] Read from blob: {file_path}")
            except Exception as blob_err:
                logger.debug(f"[FileToBase64] Blob read failed: {blob_err}")

        # Try 3: Fallback — search knowledge_base_storage directory
        if data is None:
            kb_path = config_dir / "knowledge_base_storage" / file_path
            if kb_path.exists():
                data = kb_path.read_bytes()
                logger.info(f"[FileToBase64] Read from KB storage: {kb_path}")

        if data is None:
            logger.warning(f"[FileToBase64] File not found anywhere: {file_path}")
            return None

        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return None


def _build_chat_model(model_id: str, enable_reasoning: bool = False) -> MicroserviceChatModel:
    """Create a MicroserviceChatModel for the given registry model ID.

    NOTE: provider is set to "openai" as a placeholder — the model service's
    _resolve_registry_config() will overwrite it with the actual provider
    from the registry entry before invoking the LLM.

    When enable_reasoning is True, a superset of provider-specific thinking
    params is sent via model_kwargs. The model service's provider adapters
    pick up the ones that apply (unknown keys are ignored by providers).
    """
    from agentcore.services.deps import get_settings_service
    settings = get_settings_service()

    # Provider-specific reasoning/thinking params. Because the provider is
    # resolved server-side, we send the union — each provider picks what it understands:
    #   - Anthropic Claude:  thinking={type:"enabled", budget_tokens: N}
    #   - Google Gemini:     thinking_config={include_thoughts: True}
    #   - OpenAI o1/o3/o4:   reasoning is automatic (no param)
    #   - DeepSeek-R1:       reasoning is automatic (no param)
    model_kwargs: dict | None = None
    if enable_reasoning:
        model_kwargs = {
            "thinking": {"type": "enabled", "budget_tokens": 8000},
            "thinking_config": {"include_thoughts": True},
        }

    return MicroserviceChatModel(
        service_url=settings.settings.model_service_url,
        service_api_key=settings.settings.model_service_api_key,
        registry_model_id=model_id,
        provider="openai",
        model=f"direct-chat-{model_id[:8]}",
        model_kwargs=model_kwargs,
    )


async def _build_messages_from_history(
    history: list,
    input_value: str,
    files: list[str] | None = None,
    include_system_prompt: bool = True,
) -> list:
    """Build LangChain messages from OrchConversationTable rows + current input.

    This is ONLY used for direct model chat (No Agent mode).
    When include_system_prompt=True, the system identity prompt is prepended.
    Agents have their own system prompts — this is NOT called for @agent mode.

    If files are provided (as storage paths), they are included as multimodal
    content (base64 images) in the current user message.
    """
    messages = []

    # Inject system identity prompt (only for direct model chat)
    if include_system_prompt:
        try:
            from agentcore.services.mibuddy.system_prompts import get_system_identity_prompt
            system_prompt = get_system_identity_prompt()
            if system_prompt.strip():
                messages.append(SystemMessage(content=system_prompt))
        except Exception as e:
            logger.warning(f"Failed to load system identity prompt: {e}")

    for msg in history:
        sender = getattr(msg, "sender", "") or ""
        text = getattr(msg, "text", "") or ""
        if not text:
            continue
        if sender == "user":
            messages.append(HumanMessage(content=text))
        # Both "agent" (agent-deployment responses) and "model" (direct
        # model-chat responses) are assistant turns in the LLM conversation.
        elif sender in ("agent", "model"):
            messages.append(AIMessage(content=text))

    # Build current user message with optional file attachments
    if files:
        content: list[dict] = [{"type": "text", "text": input_value}]
        for file_path in files:
            ext = Path(file_path).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                data_url = await _file_to_base64_url(file_path)
                if data_url:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    })
                else:
                    content.append({
                        "type": "text",
                        "text": f"\n[Image file could not be loaded: {file_path.split('/')[-1]}]",
                    })
            else:
                content.append({
                    "type": "text",
                    "text": f"\n[Attached file: {file_path.split('/')[-1]}]",
                })
        messages.append(HumanMessage(content=content))
    else:
        messages.append(HumanMessage(content=input_value))
    return messages


async def _get_conversation_history(session_id: str, limit: int = 20) -> list:
    """Fetch recent conversation history for a session."""
    from agentcore.services.deps import session_scope
    from agentcore.services.database.models.orch_conversation.crud import orch_get_messages

    async with session_scope() as db:
        messages = await orch_get_messages(db, session_id=session_id)
    # Return last N messages for context window
    return messages[-limit:] if len(messages) > limit else messages


async def direct_model_chat(
    *,
    model_id: str,
    input_value: str,
    session_id: str,
    files: list[str] | None = None,
    enable_reasoning: bool = False,
) -> dict:
    """Call a registry model directly and return the response.

    Returns dict with keys: response_text, reasoning_content, model_name
    """
    model = _build_chat_model(model_id, enable_reasoning=enable_reasoning)
    history = await _get_conversation_history(session_id)
    messages = await _build_messages_from_history(history, input_value, files=files)

    result = await model.ainvoke(messages)

    response_text = result.content if hasattr(result, "content") else str(result)
    metadata = getattr(result, "response_metadata", {}) or {}
    reasoning_content = metadata.get("reasoning_content")
    model_name = metadata.get("model_name", "")

    return {
        "response_text": response_text,
        "reasoning_content": reasoning_content,
        "model_name": model_name,
    }


async def direct_model_chat_stream(
    *,
    model_id: str,
    input_value: str,
    session_id: str,
    files: list[str] | None = None,
    enable_reasoning: bool = False,
    event_manager=None,
) -> dict:
    """Stream from a registry model directly, forwarding events to event_manager.

    Returns dict with keys: response_text, reasoning_content, model_name
    """
    model = _build_chat_model(model_id, enable_reasoning=enable_reasoning)
    history = await _get_conversation_history(session_id)
    messages = await _build_messages_from_history(history, input_value, files=files)

    full_response = ""
    full_reasoning = ""
    model_name = ""

    async for chunk in model.astream(messages):
        msg = chunk.message if hasattr(chunk, "message") else chunk
        raw_content = getattr(msg, "content", "")
        metadata = getattr(msg, "response_metadata", {}) or {}
        additional = getattr(msg, "additional_kwargs", {}) or {}

        # Reasoning may come from multiple places depending on provider:
        #   Anthropic: content blocks with type="thinking"
        #   Grok / DeepSeek / OpenAI o-series: additional_kwargs.reasoning_content
        #   Legacy: response_metadata.reasoning_content
        reasoning = ""
        text_content = ""
        if isinstance(raw_content, list):
            for block in raw_content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        reasoning += block.get("thinking", "")
                    elif block.get("type") == "text":
                        text_content += block.get("text", "")
        else:
            text_content = raw_content or ""

        reasoning += additional.get("reasoning_content", "") or metadata.get("reasoning_content", "")

        if reasoning:
            full_reasoning += reasoning
            if event_manager:
                event_manager.on_token(data={"chunk": reasoning, "type": "reasoning"})

        if text_content:
            full_response += text_content
            if event_manager:
                event_manager.on_token(data={"chunk": text_content})

        # Capture model name from usage metadata
        if metadata.get("model_name"):
            model_name = metadata["model_name"]

    return {
        "response_text": full_response,
        "reasoning_content": full_reasoning or None,
        "model_name": model_name,
    }
