"""Shared LTM embedding helper.

Supports both OpenAI and Azure OpenAI providers based on LTM_EMBEDDING_PROVIDER setting.
"""

from __future__ import annotations

import httpx
from loguru import logger


def _get_embedding_config() -> dict:
    """Get embedding configuration from settings."""
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    return {
        "provider": settings.ltm_embedding_provider,
        "model": settings.ltm_embedding_model,
        "api_key": settings.ltm_embedding_api_key,
        "azure_endpoint": settings.ltm_azure_openai_endpoint,
        "azure_api_version": settings.ltm_azure_openai_api_version,
        "dimensions": settings.ltm_embedding_dimensions,
    }


def _build_request(config: dict, input_data: str | list[str]) -> tuple[str, dict, dict]:
    """Build the URL, headers, and JSON body for the embedding request.

    Returns (url, headers, json_body).
    """
    provider = config["provider"]
    api_key = config["api_key"]
    model = config["model"]

    dimensions = config.get("dimensions", 0)

    if provider == "azure_openai":
        endpoint = config["azure_endpoint"].rstrip("/")
        api_version = config["azure_api_version"]
        url = f"{endpoint}/openai/deployments/{model}/embeddings?api-version={api_version}"
        headers = {"api-key": api_key, "Content-Type": "application/json"}
        body: dict = {"input": input_data}
    else:
        # Default: OpenAI
        url = "https://api.openai.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {"model": model, "input": input_data}

    # Add dimensions if configured (reduces embedding size to match Pinecone index)
    if dimensions and dimensions > 0:
        body["dimensions"] = dimensions

    return url, headers, body


async def embed_single(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    config = _get_embedding_config()
    if not config["api_key"]:
        logger.error("[LTM] LTM_EMBEDDING_API_KEY is empty — cannot generate embeddings")
        return []

    url, headers, body = _build_request(config, text)
    provider = config["provider"]
    logger.debug(f"[LTM] Embedding single: provider={provider}, model={config['model']}, key={'***' + config['api_key'][-4:] if len(config['api_key']) > 4 else '(short)'}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        error_detail = ""
        try:
            error_detail = e.response.text[:500]
        except Exception:
            error_detail = str(e)
        logger.error(f"[LTM] Embedding HTTP error: {e.response.status_code} | {error_detail}")
        return []
    except Exception as e:
        logger.error(f"[LTM] Embedding request failed: {type(e).__name__}: {e}")
        return []

    data = resp.json()
    logger.debug(f"[LTM] Embedding generated via {provider}")
    return data["data"][0]["embedding"] if data.get("data") else []


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single API call."""
    config = _get_embedding_config()
    if not config["api_key"]:
        logger.error("[LTM] LTM_EMBEDDING_API_KEY is empty — cannot generate embeddings")
        return []

    url, headers, body = _build_request(config, texts)
    logger.debug(f"[LTM] Embedding request: provider={config['provider']}, model={config['model']}, texts={len(texts)}, url={url}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        error_detail = ""
        try:
            error_detail = e.response.text[:500]
        except Exception:
            error_detail = str(e)
        logger.error(f"[LTM] Embedding HTTP error: {e.response.status_code} | {error_detail}")
        return []
    except Exception as e:
        logger.error(f"[LTM] Embedding request failed: {type(e).__name__}: {e}")
        return []

    data = resp.json()
    return [item["embedding"] for item in data.get("data", [])]
