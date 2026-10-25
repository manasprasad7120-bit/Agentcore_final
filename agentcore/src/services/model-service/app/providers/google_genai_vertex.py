"""Google GenAI (Vertex AI) provider — MiBuddy-parity.

Wraps the unified `google-genai` SDK with `vertexai=True` so ALL Gemini
traffic (chat completion AND web-search grounding) routes through Vertex AI
(`aiplatform.googleapis.com`). Matches MiBuddy's pattern at
`MiBuddy-Backend/backend/utils/gemini_service.py`:

    from google import genai
    client = genai.Client(vertexai=True, api_key=GOOGLE_CLOUD_API_KEY)

Unlike the existing `google_vertex` provider — which routes AQ.* Express
API keys through this same SDK but falls through to
`langchain-google-vertexai.ChatVertexAI` (service-account + project_id)
for every other key format — this provider uses the `google-genai` SDK
unconditionally. Works with any API key that has Vertex AI access, without
requiring a service-account JSON or explicit `project_id`.

Register a model with:
  provider: "google_genai_vertex"
  model_name: "gemini-3-pro-preview" (or any Vertex AI model)
  api_key: your Google API key

Motivation: avoids the `generativelanguage.googleapis.com` 403 error that
occurs with the `google` provider when that API isn't enabled on the GCP
project. Same endpoint `web_search_handler.py` already uses successfully.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.providers.base import BaseProvider, register_provider

logger = logging.getLogger(__name__)


class _GenAIVertexChatModel(BaseChatModel):
    """LangChain chat-model wrapper around `google-genai` with vertexai=True.

    Supports both synchronous and async invocation, plus token-by-token
    streaming. The `google-genai` SDK is synchronous; async methods bridge
    via `asyncio.to_thread` so they don't block the event loop.
    """

    model: str
    api_key: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None

    @property
    def _llm_type(self) -> str:
        return "google-genai-vertex"

    # ------- helpers -------

    def _build_client(self):
        from google import genai

        return genai.Client(vertexai=True, api_key=self.api_key)

    def _convert_messages(self, messages):
        """Map LangChain BaseMessage list → google-genai Content list.

        System messages are flattened into the next HumanMessage as a
        prefix (google-genai accepts "system_instruction" on the config
        object but folding here keeps the logic simple and matches the
        approach used by `_VertexExpressChatModel`).
        """
        from google.genai import types

        contents: list = []
        system_text = ""
        for msg in messages:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if isinstance(msg, SystemMessage):
                system_text += text + "\n"
            elif isinstance(msg, HumanMessage):
                if system_text:
                    text = f"SYSTEM INSTRUCTIONS:\n{system_text}\n\n{text}"
                    system_text = ""
                contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
            elif isinstance(msg, AIMessage):
                contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
        return contents

    def _build_config(self):
        from google.genai import types

        return types.GenerateContentConfig(
            temperature=self.temperature if self.temperature is not None else 1.0,
            top_p=self.top_p if self.top_p is not None else 0.95,
            max_output_tokens=self.max_output_tokens or 8192,
        )

    @staticmethod
    def _extract_usage(response) -> dict | None:
        """Pull token counts off a google-genai response in LangChain's format."""
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return None
        prompt = getattr(usage, "prompt_token_count", 0) or 0
        candidates = getattr(usage, "candidates_token_count", 0) or 0
        total = getattr(usage, "total_token_count", 0) or (prompt + candidates)
        return {
            "input_tokens": prompt,
            "output_tokens": candidates,
            "total_tokens": total,
        }

    # ------- sync path -------

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        client = self._build_client()
        response = client.models.generate_content(
            model=self.model,
            contents=self._convert_messages(messages),
            config=self._build_config(),
        )
        text = response.text or ""
        ai_msg = AIMessage(content=text)
        usage = self._extract_usage(response)
        if usage:
            # LangChain AIMessage accepts usage_metadata via attribute assignment.
            try:
                ai_msg.usage_metadata = usage  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    # ------- async path -------

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return await asyncio.to_thread(self._generate, messages, stop, run_manager, **kwargs)

    # ------- streaming -------

    def _stream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> Iterator[ChatGenerationChunk]:
        client = self._build_client()
        stream = client.models.generate_content_stream(
            model=self.model,
            contents=self._convert_messages(messages),
            config=self._build_config(),
        )
        for chunk in stream:
            text = getattr(chunk, "text", "") or ""
            if not text:
                continue
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async token-by-token streaming bridged from the sync SDK generator.

        `asyncio.to_thread(next, iterator)` pulls each chunk off the sync
        generator in a worker thread so the event loop stays responsive.
        Falls back to a full non-stream response on SDK errors.
        """
        from google import genai
        from google.genai import types  # noqa: F401  (keeps types imported for potential future use)

        def _open_stream():
            client = self._build_client()
            return client.models.generate_content_stream(
                model=self.model,
                contents=self._convert_messages(messages),
                config=self._build_config(),
            )

        try:
            stream = await asyncio.to_thread(_open_stream)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[google_genai_vertex] stream open failed, falling back: {exc}")
            result = await self._agenerate(messages, stop, run_manager, **kwargs)
            for gen in result.generations:
                yield ChatGenerationChunk(
                    message=AIMessageChunk(content=gen.message.content)
                )
            return

        iterator = iter(stream)
        while True:
            try:
                chunk = await asyncio.to_thread(next, iterator)
            except StopIteration:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[google_genai_vertex] mid-stream error: {exc}")
                break
            text = getattr(chunk, "text", "") or ""
            if text:
                yield ChatGenerationChunk(message=AIMessageChunk(content=text))


@register_provider("google_genai_vertex")
class GoogleGenAIVertexProvider(BaseProvider):
    """MiBuddy-parity Gemini provider using `google-genai` SDK + `vertexai=True`.

    Routes ALL Gemini traffic through Vertex AI (`aiplatform.googleapis.com`)
    with a single unified SDK. See module docstring for why this exists
    alongside the `google` and `google_vertex` providers.
    """

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        return [
            "gemini-3-pro-preview",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
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
        api_key = (provider_config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError(
                "google_genai_vertex provider requires `api_key` in provider_config. "
                "Use any Google API key with Vertex AI access."
            )
        return _GenAIVertexChatModel(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
        )
