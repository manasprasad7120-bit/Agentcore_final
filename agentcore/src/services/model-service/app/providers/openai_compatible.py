import logging
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.providers.base import BaseProvider, register_provider

logger = logging.getLogger(__name__)


@register_provider("openai_compatible")
class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible provider (Tier 2).

    Works with any provider that exposes an OpenAI-compatible chat completions API:
    Ollama, DeepSeek, Together, Fireworks, Mistral, vLLM, NVIDIA NIM, OpenRouter, etc.
    """

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url", "")
        if not base_url:
            return []
        try:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            custom_headers = provider_config.get("custom_headers", {})
            if custom_headers:
                headers.update(custom_headers)

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                return sorted([m["id"] for m in data.get("data", [])])
        except Exception as e:
            logger.warning("Failed to list models from %s: %s", base_url, e)
            return []

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
        base_url = provider_config.get("base_url", "")

        if not base_url:
            msg = "base_url is required for openai_compatible provider"
            raise ValueError(msg)

        # stream_usage adds stream_options.include_usage to the request. Some
        # endpoints (Azure AI Foundry serverless) reject this field. Most standard
        # OpenAI-compatible endpoints (DeepSeek, Groq, OpenRouter) accept it.
        # Default: False (safe for strict endpoints); users can opt-in via
        # provider_config.stream_usage=True in the registry entry.
        stream_usage = bool(provider_config.get("stream_usage", False))

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key or "not-needed",
            "base_url": base_url,
            "streaming": streaming,
            "stream_usage": stream_usage,
        }

        if temperature is not None:
            kwargs["temperature"] = temperature

        # Azure AI Foundry serverless (Mistral, Grok, etc.) rejects `max_completion_tokens`,
        # but newer langchain-openai auto-converts `max_tokens` → `max_completion_tokens`.
        # Bypass the conversion by sending `max_tokens` via extra_body (raw passthrough).
        extra_body: dict[str, Any] = {}
        if max_tokens:
            extra_body["max_tokens"] = max_tokens

        if seed is not None:
            kwargs["seed"] = seed
        if model_kwargs:
            # OpenAI-compatible APIs (Grok, DeepSeek, OpenRouter, etc.) do NOT
            # accept Anthropic's `thinking` / `thinking_config` kwargs. Strip
            # them out so the OpenAI SDK doesn't raise TypeError.
            cleaned = {
                k: v for k, v in model_kwargs.items()
                if k not in ("thinking", "thinking_config")
            }
            if cleaned:
                kwargs["model_kwargs"] = cleaned

        custom_headers = provider_config.get("custom_headers")
        if custom_headers:
            kwargs["default_headers"] = custom_headers

        if extra_body:
            kwargs["extra_body"] = extra_body

        llm = ChatOpenAI(**kwargs)

        if json_mode:
            llm = llm.bind(response_format={"type": "json_object"})

        return llm

    def build_embeddings(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        dimensions: int | None = None,
    ) -> OpenAIEmbeddings:
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url", "")

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key or "not-needed",
        }
        if base_url:
            kwargs["base_url"] = base_url
        if dimensions:
            kwargs["dimensions"] = dimensions
        custom_headers = provider_config.get("custom_headers", {})
        if custom_headers:
            kwargs["default_headers"] = custom_headers
        return OpenAIEmbeddings(**kwargs)
