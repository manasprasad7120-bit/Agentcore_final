import json
import logging
from typing import AsyncIterator
from uuid import UUID

from langchain_core.messages import AIMessage

from app.providers.base import get_provider
from app.schemas import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChoiceMessage,
    ChunkChoice,
    DeltaMessage,
    ToolCall,
    ToolCallFunction,
    UsageInfo,
)
from app.services.rate_limiter import NULL_CONTEXT, RateLimitContext

logger = logging.getLogger(__name__)


def _extract_usage(message: AIMessage) -> UsageInfo:
    """Extract token usage from an AIMessage, normalizing across provider formats."""
    metadata = getattr(message, "response_metadata", {}) or {}
    usage_metadata = getattr(message, "usage_metadata", {}) or {}

    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    # OpenAI / Groq / Azure format: response_metadata.token_usage
    token_usage = metadata.get("token_usage", {})
    if token_usage:
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)
        total_tokens = token_usage.get("total_tokens", 0)

    # Anthropic format: response_metadata.usage
    elif "usage" in metadata:
        usage = metadata["usage"]
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        total_tokens = prompt_tokens + completion_tokens

    # Google Gemini format: response_metadata.usage_metadata
    elif "usage_metadata" in metadata:
        usage = metadata["usage_metadata"]
        prompt_tokens = usage.get("prompt_token_count", 0)
        completion_tokens = usage.get("candidates_token_count", 0)
        total_tokens = usage.get("total_token_count", prompt_tokens + completion_tokens)

    # LangChain built-in usage_metadata on the message itself
    elif usage_metadata:
        prompt_tokens = usage_metadata.get("input_tokens", 0)
        completion_tokens = usage_metadata.get("output_tokens", 0)
        total_tokens = usage_metadata.get("total_tokens", prompt_tokens + completion_tokens)

    return UsageInfo(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _extract_finish_reason(message: AIMessage) -> str:
    """Extract and normalize the finish reason from an AIMessage."""
    metadata = getattr(message, "response_metadata", {}) or {}

    reason = metadata.get("finish_reason") or metadata.get("stop_reason") or "stop"

    # Normalize common variants
    reason_lower = str(reason).lower()
    if reason_lower in ("stop", "end_turn", "eos", "finish"):
        return "stop"
    if reason_lower in ("length", "max_tokens"):
        return "length"
    return reason_lower


async def _resolve_registry_config(request: ChatCompletionRequest) -> ChatCompletionRequest:
    """If the request references a registry model, resolve the full config from DB."""
    registry_model_id = request.provider_config.get("registry_model_id")
    if not registry_model_id:
        return request

    from app.database import get_session
    from app.services.registry_service import get_decrypted_config

    async for session in get_session():
        config = await get_decrypted_config(session, UUID(str(registry_model_id)))

    if config is None:
        msg = f"Registry model {registry_model_id} not found"
        raise ValueError(msg)

    # Build merged provider_config from registry data
    provider_config = dict(config.get("provider_config", {}))
    provider_config["api_key"] = config["api_key"]
    if config.get("base_url"):
        provider_config["base_url"] = config["base_url"]
        # Azure needs azure_endpoint too
        if config["provider"] == "azure":
            provider_config.setdefault("azure_endpoint", config["base_url"])

    # Apply default params from registry (request params override)
    defaults = config.get("default_params", {})

    return ChatCompletionRequest(
        provider=config["provider"],
        model=config["model_name"],
        messages=request.messages,
        provider_config=provider_config,
        temperature=request.temperature if request.temperature is not None else defaults.get("temperature"),
        max_tokens=request.max_tokens if request.max_tokens is not None else defaults.get("max_tokens"),
        top_p=request.top_p if request.top_p is not None else defaults.get("top_p"),
        top_k=request.top_k if request.top_k is not None else defaults.get("top_k"),
        n=request.n,
        stream=request.stream,
        seed=request.seed,
        json_mode=request.json_mode,
        model_kwargs=request.model_kwargs or defaults.get("model_kwargs"),
        tools=request.tools,
    )


def _extract_reasoning(raw_content, ai_message: AIMessage) -> tuple[str, str | None]:
    """Extract reasoning/thinking content from an AIMessage.

    Returns (content, reasoning_content).

    Anthropic extended thinking returns content as a list of blocks:
      [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "..."}]
    OpenAI o1/o3 and DeepSeek put reasoning in additional_kwargs.reasoning_content.
    """
    reasoning_content: str | None = None

    # Anthropic: content is a list of content blocks
    if isinstance(raw_content, list):
        text_parts = []
        thinking_parts = []
        for block in raw_content:
            if isinstance(block, dict):
                if block.get("type") == "thinking":
                    thinking_parts.append(block.get("thinking", ""))
                elif block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                else:
                    text_parts.append(str(block.get("text", block.get("content", ""))))
            elif hasattr(block, "type"):
                if block.type == "thinking":
                    thinking_parts.append(getattr(block, "thinking", ""))
                elif block.type == "text":
                    text_parts.append(getattr(block, "text", ""))
        content = "\n".join(text_parts)
        if thinking_parts:
            reasoning_content = "\n".join(thinking_parts)
        return content, reasoning_content

    content = str(raw_content) if raw_content else ""

    # OpenAI o1/o3, DeepSeek: reasoning in additional_kwargs
    additional_kwargs = getattr(ai_message, "additional_kwargs", {}) or {}
    if additional_kwargs.get("reasoning_content"):
        reasoning_content = additional_kwargs["reasoning_content"]

    # Also check response_metadata for reasoning
    metadata = getattr(ai_message, "response_metadata", {}) or {}
    if not reasoning_content and metadata.get("reasoning_content"):
        reasoning_content = metadata["reasoning_content"]

    # Google Gemini: thinking in metadata.thoughts or additional_kwargs.thoughts
    if not reasoning_content:
        thoughts = additional_kwargs.get("thoughts") or metadata.get("thoughts")
        if thoughts:
            if isinstance(thoughts, list):
                reasoning_content = "\n".join(str(t) for t in thoughts)
            else:
                reasoning_content = str(thoughts)

    return content, reasoning_content


async def chat_completion(
    request: ChatCompletionRequest,
    rate_limit_ctx: RateLimitContext = NULL_CONTEXT,
) -> ChatCompletionResponse:
    """Process a non-streaming chat completion request."""
    request = await _resolve_registry_config(request)
    provider = get_provider(request.provider.value)

    model = provider.build_model(
        model=request.model,
        provider_config=request.provider_config,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        top_p=request.top_p,
        top_k=request.top_k,
        n=request.n,
        streaming=False,
        seed=request.seed,
        json_mode=request.json_mode,
        model_kwargs=request.model_kwargs,
    )

    # Bind tools if provided
    if request.tools:
        model = model.bind_tools(request.tools)

    messages = provider.build_messages([m.model_dump() for m in request.messages])

    ai_message = await provider.invoke(model, messages)

    raw_content = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
    content, reasoning_content = _extract_reasoning(raw_content, ai_message)
    usage = _extract_usage(ai_message)
    finish_reason = _extract_finish_reason(ai_message)

    # Post-flight TPM debit. The pre-flight check in the dependency only
    # verified there was room; we charge actual provider tokens here.
    await rate_limit_ctx.debit_tpm(usage.total_tokens)

    # Extract tool calls from the AIMessage
    tool_calls_out: list[ToolCall] | None = None
    lc_tool_calls = getattr(ai_message, "tool_calls", None)
    if lc_tool_calls:
        tool_calls_out = []
        for tc in lc_tool_calls:
            tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
            tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            tool_calls_out.append(
                ToolCall(
                    id=tc_id,
                    function=ToolCallFunction(
                        name=tc_name,
                        arguments=json.dumps(tc_args) if isinstance(tc_args, dict) else str(tc_args),
                    ),
                )
            )
        finish_reason = "tool_calls"

    return ChatCompletionResponse(
        model=request.model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChoiceMessage(
                    role="assistant",
                    content=content or "",
                    tool_calls=tool_calls_out,
                    reasoning_content=reasoning_content,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


async def chat_completion_stream(
    request: ChatCompletionRequest,
    rate_limit_ctx: RateLimitContext = NULL_CONTEXT,
) -> AsyncIterator[str]:
    """Process a streaming chat completion request, yielding SSE-formatted strings."""
    request = await _resolve_registry_config(request)
    provider = get_provider(request.provider.value)

    model = provider.build_model(
        model=request.model,
        provider_config=request.provider_config,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        top_p=request.top_p,
        top_k=request.top_k,
        n=request.n,
        streaming=True,
        seed=request.seed,
        json_mode=request.json_mode,
        model_kwargs=request.model_kwargs,
    )

    # Bind tools if provided (mirrors the non-streaming path)
    if request.tools:
        model = model.bind_tools(request.tools)

    messages = provider.build_messages([m.model_dump() for m in request.messages])

    # ``accumulated`` is hoisted above the try/finally so the debit in
    # ``finally`` can charge whatever tokens were consumed even if the client
    # disconnects mid-stream (which surfaces here as GeneratorExit).
    accumulated = None
    finish_reason = "stop"
    _logged_shape = False
    try:
        # Send initial chunk with role
        initial_chunk = ChatCompletionChunk(
            model=request.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(role="assistant", content=""),
                )
            ],
        )
        yield f"data: {initial_chunk.model_dump_json()}\n\n"

        async for chunk in provider.stream(model, messages):
            # Accumulate chunks so the final message carries usage metadata
            try:
                accumulated = chunk if accumulated is None else accumulated + chunk
            except TypeError:
                pass

            content = ""
            reasoning = ""

            # Check for reasoning content in streaming chunks.
            #   Anthropic extended thinking: content blocks with type="thinking"
            #   Google Gemini (langchain-google-genai): content blocks with thought=True,
            #     OR additional_kwargs.thoughts / thinking_content
            #   OpenAI o-series / DeepSeek-R1 / Grok: additional_kwargs.reasoning_content
            raw = chunk.content if hasattr(chunk, "content") else chunk
            if isinstance(raw, list):
                for block in raw:
                    if isinstance(block, dict):
                        # Gemini marks thought parts with thought=True regardless of
                        # the block's "type" field. Check this FIRST so a thought
                        # block isn't accidentally counted as user-facing content.
                        if block.get("thought") is True:
                            reasoning += block.get("text", "") or block.get("thinking", "")
                            continue
                        if block.get("type") == "thinking":
                            reasoning += block.get("thinking", "")
                        elif block.get("type") == "text":
                            content += block.get("text", "")
                    elif hasattr(block, "type") or hasattr(block, "thought"):
                        # Object-style content block (some langchain providers)
                        if getattr(block, "thought", False) is True:
                            reasoning += getattr(block, "text", "") or getattr(block, "thinking", "")
                            continue
                        if getattr(block, "type", None) == "thinking":
                            reasoning += getattr(block, "thinking", "")
                        elif getattr(block, "type", None) == "text":
                            content += getattr(block, "text", "")
            elif raw:
                content = str(raw) if not isinstance(raw, str) else raw

            # OpenAI/DeepSeek: reasoning in additional_kwargs
            additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
            if additional_kwargs.get("reasoning_content"):
                reasoning = additional_kwargs["reasoning_content"]
            # Gemini surfaces thoughts in additional_kwargs in some
            # langchain-google-genai versions. Append (don't overwrite) so we don't
            # clobber thoughts already extracted from content blocks above.
            for _gemini_key in ("thoughts", "thinking_content", "thought_content"):
                _val = additional_kwargs.get(_gemini_key)
                if not _val:
                    continue
                if isinstance(_val, list):
                    reasoning += "".join(str(p) for p in _val if p)
                else:
                    reasoning += str(_val)

            # One-shot diagnostic on the first chunk that declared reasoning intent.
            # Prints the shape that landed so we can adjust the extractor for new
            # provider versions without guessing.
            if not _logged_shape:
                try:
                    from loguru import logger as _logger
                    _content_preview = (
                        raw[:2] if isinstance(raw, list) else str(raw)[:120]
                    )
                    _logger.info(
                        f"[ModelSvcStream][reasoning-debug] first_chunk content_type={type(raw).__name__} "
                        f"content_preview={_content_preview!r} "
                        f"additional_kwargs_keys={list(additional_kwargs.keys())} "
                        f"extracted_reasoning_len={len(reasoning)} extracted_content_len={len(content)}"
                    )
                except Exception:  # noqa: BLE001
                    pass
                _logged_shape = True

            if reasoning:
                reasoning_chunk = ChatCompletionChunk(
                    model=request.model,
                    choices=[
                        ChunkChoice(
                            index=0,
                            delta=DeltaMessage(reasoning_content=reasoning),
                        )
                    ],
                )
                yield f"data: {reasoning_chunk.model_dump_json()}\n\n"

            if content:
                stream_chunk = ChatCompletionChunk(
                    model=request.model,
                    choices=[
                        ChunkChoice(
                            index=0,
                            delta=DeltaMessage(content=content),
                        )
                    ],
                )
                yield f"data: {stream_chunk.model_dump_json()}\n\n"

            # Stream tool call deltas so the client can reconstruct tool calls
            tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
            if tool_call_chunks:
                tc_deltas = []
                for tc_chunk in tool_call_chunks:
                    tc_dict: dict = {}
                    if isinstance(tc_chunk, dict):
                        tc_dict = {
                            "index": tc_chunk.get("index", 0),
                            "id": tc_chunk.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc_chunk.get("name", ""),
                                "arguments": tc_chunk.get("args", ""),
                            },
                        }
                    else:
                        tc_dict = {
                            "index": getattr(tc_chunk, "index", 0),
                            "id": getattr(tc_chunk, "id", ""),
                            "type": "function",
                            "function": {
                                "name": getattr(tc_chunk, "name", ""),
                                "arguments": getattr(tc_chunk, "args", ""),
                            },
                        }
                    tc_deltas.append(tc_dict)

                tc_stream_chunk = ChatCompletionChunk(
                    model=request.model,
                    choices=[
                        ChunkChoice(
                            index=0,
                            delta=DeltaMessage(tool_calls=tc_deltas),
                        )
                    ],
                )
                yield f"data: {tc_stream_chunk.model_dump_json()}\n\n"
                finish_reason = "tool_calls"

        # If the accumulated message has tool_calls but none were streamed
        # (some providers only expose them on the final accumulated message),
        # send them now so the client can reconstruct them.
        if accumulated is not None:
            lc_tool_calls = getattr(accumulated, "tool_calls", None)
            if lc_tool_calls and finish_reason != "tool_calls":
                tc_list = []
                for tc in lc_tool_calls:
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                    tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    tc_list.append({
                        "index": 0,
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tc_name,
                            "arguments": json.dumps(tc_args) if isinstance(tc_args, dict) else str(tc_args),
                        },
                    })
                tc_final_chunk = ChatCompletionChunk(
                    model=request.model,
                    choices=[
                        ChunkChoice(
                            index=0,
                            delta=DeltaMessage(tool_calls=tc_list),
                        )
                    ],
                )
                yield f"data: {tc_final_chunk.model_dump_json()}\n\n"
                finish_reason = "tool_calls"

        # Send final chunk with finish_reason
        final_chunk = ChatCompletionChunk(
            model=request.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(),
                    finish_reason=finish_reason,
                )
            ],
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"

        # Extract and send usage from accumulated message
        if accumulated is not None:
            usage = _extract_usage(accumulated)
            if usage.prompt_tokens or usage.completion_tokens or usage.total_tokens:
                usage_chunk = ChatCompletionChunk(
                    model=request.model,
                    choices=[],
                    usage=usage,
                )
                yield f"data: {usage_chunk.model_dump_json()}\n\n"

        yield "data: [DONE]\n\n"
    finally:
        # Best-effort TPM debit -- runs on the happy path AND on client
        # disconnect (GeneratorExit). debit_tpm itself swallows Redis errors so
        # nothing here can break the response that already shipped.
        if accumulated is not None:
            try:
                final_usage = _extract_usage(accumulated)
                if final_usage.total_tokens > 0:
                    await rate_limit_ctx.debit_tpm(final_usage.total_tokens)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to debit TPM after streaming chat completion")
