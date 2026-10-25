"""Google Vertex AI provider for chat models.

Supports TWO authentication modes:
  1. Service account JSON (file path or inline) — full Vertex AI access, needs project_id
  2. Vertex AI Express API key (starts with "AQ.") — simpler, no project_id required

Register a model with:
  provider: "google_vertex"
  model_name: "gemini-2.5-flash" (or any Vertex AI model)
  api_key: path/inline service account JSON OR Vertex Express API key (AQ.*)
  provider_config: {
    "project_id": "your-gcp-project",     # required for service account auth
    "location": "us-central1"
  }
"""

import json
import logging
import os
import tempfile
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.providers.base import BaseProvider, register_provider

logger = logging.getLogger(__name__)


def _is_express_api_key(value: str) -> bool:
    """Detect Vertex AI Express API key (e.g. 'AQ.Ab8RN6IC...')."""
    if not value:
        return False
    v = value.strip()
    # Express keys are ~40+ chars, start with 'AQ.' and are NOT JSON nor file paths
    return v.startswith("AQ.") and not v.startswith("{") and not os.path.exists(v)


class _VertexExpressChatModel(BaseChatModel):
    """Minimal BaseChatModel wrapper using google-genai SDK with vertexai=True + api_key.

    Used when the user provides a Vertex AI Express API key instead of a service account.
    Avoids the service-account-only limitation of langchain-google-vertexai.ChatVertexAI.

    Supports Gemini 2.5+/3.x visible thinking when ``model_kwargs`` carries
    ``thinking_config={"include_thoughts": True}`` (and optionally
    ``thinking_budget``). Thought parts are emitted as separate AIMessageChunks
    whose ``additional_kwargs["reasoning_content"]`` carries the thought text;
    the model service's streaming loop already lifts that into the SSE
    ``reasoning_content`` delta.
    """

    model: str
    api_key: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    # Free-form passthrough so callers can plumb thinking_config / system_instruction / etc.
    model_kwargs: dict | None = None

    @property
    def _llm_type(self) -> str:
        return "google-vertex-express"

    def _convert_messages(self, messages):
        from google.genai import types
        contents = []
        system_text = ""
        for msg in messages:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if isinstance(msg, SystemMessage):
                system_text += text + "\n"
            elif isinstance(msg, HumanMessage):
                role = "user"
                if system_text:
                    text = f"SYSTEM INSTRUCTIONS:\n{system_text}\n\n{text}"
                    system_text = ""
                contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
            elif isinstance(msg, AIMessage):
                contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
        return contents

    def _build_config(self):
        """Build GenerateContentConfig, attaching thinking_config when requested."""
        from google.genai import types

        cfg_kwargs: dict[str, Any] = {
            "temperature": self.temperature if self.temperature is not None else 1.0,
            "top_p": self.top_p if self.top_p is not None else 0.95,
            "max_output_tokens": self.max_output_tokens or 8192,
        }

        # Thinking config plumb-through. Caller passes:
        #   model_kwargs={"thinking_config": {"include_thoughts": True, "thinking_budget": -1}}
        thinking_config_in = (self.model_kwargs or {}).get("thinking_config")
        if thinking_config_in:
            try:
                # Newer google-genai exposes ThinkingConfig with optional thinking_budget.
                tc_kwargs: dict[str, Any] = {}
                if "include_thoughts" in thinking_config_in:
                    tc_kwargs["include_thoughts"] = bool(thinking_config_in["include_thoughts"])
                if "thinking_budget" in thinking_config_in:
                    tc_kwargs["thinking_budget"] = int(thinking_config_in["thinking_budget"])
                try:
                    cfg_kwargs["thinking_config"] = types.ThinkingConfig(**tc_kwargs)
                except TypeError:
                    # Older SDKs accept only include_thoughts.
                    cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                        include_thoughts=tc_kwargs.get("include_thoughts", True),
                    )
                logger.info(
                    "[VertexExpress] thinking_config attached: %r",
                    cfg_kwargs["thinking_config"],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[VertexExpress] failed to attach thinking_config: %s", e)

        return types.GenerateContentConfig(**cfg_kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from google import genai

        client = genai.Client(vertexai=True, api_key=self.api_key)
        config = self._build_config()
        response = client.models.generate_content(
            model=self.model,
            contents=self._convert_messages(messages),
            config=config,
        )

        # Walk parts so thoughts (if any) end up in additional_kwargs.reasoning_content
        # — same shape we emit during streaming so downstream extractors are uniform.
        full_text = ""
        full_thoughts = ""
        try:
            cands = getattr(response, "candidates", None) or []
            if cands and getattr(cands[0], "content", None):
                for part in cands[0].content.parts:
                    part_text = getattr(part, "text", "") or ""
                    if not part_text:
                        continue
                    if getattr(part, "thought", False):
                        full_thoughts += part_text
                    else:
                        full_text += part_text
        except Exception as e:  # noqa: BLE001
            logger.debug("[VertexExpress] _generate part-walk fell back to .text: %s", e)
            full_text = response.text or ""

        if not full_text:
            full_text = response.text or full_text

        msg = AIMessage(
            content=full_text,
            additional_kwargs={"reasoning_content": full_thoughts} if full_thoughts else {},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # google-genai SDK is sync; run in a thread
        import asyncio
        return await asyncio.to_thread(self._generate, messages, stop, run_manager, **kwargs)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        """Stream tokens, splitting thought parts from answer parts.

        Thought parts are emitted as AIMessageChunks with
        ``additional_kwargs={"reasoning_content": <text>}`` and empty content,
        so the model service's streaming loop forwards them as
        ``reasoning_content`` SSE deltas.
        """
        from google import genai
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        client = genai.Client(vertexai=True, api_key=self.api_key)
        config = self._build_config()

        first_logged = False
        try:
            for chunk in client.models.generate_content_stream(
                model=self.model,
                contents=self._convert_messages(messages),
                config=config,
            ):
                cands = getattr(chunk, "candidates", None) or []
                if not cands:
                    continue
                content_obj = getattr(cands[0], "content", None)
                if content_obj is None:
                    continue
                for part in getattr(content_obj, "parts", None) or []:
                    part_text = getattr(part, "text", "") or ""
                    if not part_text:
                        continue
                    is_thought = bool(getattr(part, "thought", False))
                    if not first_logged:
                        logger.info(
                            "[VertexExpress] first stream part: thought=%s len=%d preview=%r",
                            is_thought,
                            len(part_text),
                            part_text[:80],
                        )
                        first_logged = True
                    if is_thought:
                        msg_chunk = AIMessageChunk(
                            content="",
                            additional_kwargs={"reasoning_content": part_text},
                        )
                    else:
                        msg_chunk = AIMessageChunk(content=part_text)
                    gen_chunk = ChatGenerationChunk(message=msg_chunk)
                    if run_manager and not is_thought:
                        run_manager.on_llm_new_token(part_text, chunk=gen_chunk)
                    yield gen_chunk
        except Exception as e:  # noqa: BLE001
            logger.error("[VertexExpress] stream failed: %s", e)
            raise

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        """Async streaming — google-genai's sync stream forwarded chunk-by-chunk."""
        import asyncio
        # The genai sync iterator can't be awaited directly. Pull chunks in a
        # worker thread and forward them through an asyncio.Queue.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def _produce():
            try:
                for c in self._stream(messages, stop=stop, run_manager=None, **kwargs):
                    asyncio.run_coroutine_threadsafe(queue.put(c), loop)
            except Exception as exc:  # noqa: BLE001
                asyncio.run_coroutine_threadsafe(queue.put(("__error__", exc)), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop)

        await loop.run_in_executor(None, _produce)
        # Note: run_in_executor returns when _produce finishes, so we can drain
        # synchronously here. For huge streams a true producer task would be
        # better, but Vertex chunks are small enough that this is fine.
        while True:
            item = await queue.get()
            if item is SENTINEL:
                break
            if isinstance(item, tuple) and item[0] == "__error__":
                raise item[1]
            yield item


def _resolve_credentials(api_key_or_path: str):
    """Resolve service account credentials from path or inline JSON."""
    from google.oauth2 import service_account

    sa_path = api_key_or_path
    temp_file = None

    # If api_key is inline JSON, write to temp file
    if api_key_or_path.strip().startswith("{"):
        try:
            sa_data = json.loads(api_key_or_path)
            temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump(sa_data, temp_file)
            temp_file.close()
            sa_path = temp_file.name
        except json.JSONDecodeError:
            pass

    if not os.path.exists(sa_path):
        raise ValueError(f"Service account file not found: {sa_path}")

    credentials = service_account.Credentials.from_service_account_file(
        sa_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    # Clean up temp file
    if temp_file:
        try:
            os.unlink(temp_file.name)
        except OSError:
            pass

    return credentials


@register_provider("google_vertex")
class GoogleVertexProvider(BaseProvider):
    """Google Vertex AI provider using service account authentication."""

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        """Return commonly available Vertex AI Gemini models."""
        return [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-2.5-flash-image",
        ]

    def build_model(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        n: int | None = None,
        streaming: bool = False,
        seed: int | None = None,
        json_mode: bool = False,
        model_kwargs: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        api_key = provider_config.get("api_key", "")
        project_id = provider_config.get("project_id", "")
        location = provider_config.get("location", "us-central1")

        # Mode 1: Vertex AI Express API key (e.g. "AQ.Ab8RN6IC...") — no project_id needed
        if _is_express_api_key(api_key):
            logger.info("Using Vertex AI Express API key auth for model=%s", model)
            # Strip Anthropic-only kwargs before handing to the Gemini wrapper.
            # Keep thinking_config (Gemini understands it) and any other
            # generic kwargs the caller might add later.
            mk: dict[str, Any] | None = None
            if model_kwargs:
                mk = {k: v for k, v in model_kwargs.items() if k != "thinking"}
            return _VertexExpressChatModel(
                model=model,
                api_key=api_key,
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=top_p,
                top_k=top_k,
                model_kwargs=mk,
            )

        # Mode 2: Service account JSON — requires project_id
        from langchain_google_vertexai import ChatVertexAI

        if not project_id:
            raise ValueError(
                "provider_config.project_id is required for Vertex AI service account auth. "
                "Or use a Vertex AI Express API key (starts with 'AQ.')."
            )

        kwargs: dict[str, Any] = {
            "model_name": model,
            "project": project_id,
            "location": location,
            "streaming": streaming,
        }

        if api_key:
            credentials = _resolve_credentials(api_key)
            kwargs["credentials"] = credentials

        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens
        if top_p is not None:
            kwargs["top_p"] = top_p
        if top_k is not None:
            kwargs["top_k"] = top_k
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs

        return ChatVertexAI(**kwargs)
