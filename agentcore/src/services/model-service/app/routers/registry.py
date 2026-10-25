"""REST endpoints for the model registry."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.models.registry import (
    ModelRegistryCreate,
    ModelRegistryRead,
    ModelRegistryUpdate,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.providers.base import get_provider
from app.services import registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/registry", tags=["registry"])
# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/models", response_model=list[ModelRegistryRead])
async def list_registry_models(
    provider: str | None = None,
    environment: str | None = None,
    model_type: str | None = None,
    active_only: bool = True,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List all registered models, optionally filtered by provider, environment, and/or model type."""
    return await registry_service.get_models(
        session, provider=provider, environment=environment, model_type=model_type, active_only=active_only
    )


@router.post("/models", response_model=ModelRegistryRead, status_code=201)
async def create_registry_model(
    body: ModelRegistryCreate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Register a new model."""
    return await registry_service.create_model(session, body)


@router.get("/models/{model_id}", response_model=ModelRegistryRead)
async def get_registry_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Get a single registered model by ID."""
    model = await registry_service.get_model(session, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.put("/models/{model_id}", response_model=ModelRegistryRead)
async def update_registry_model(
    model_id: UUID,
    body: ModelRegistryUpdate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Update an existing registered model."""
    model = await registry_service.update_model(session, model_id, body)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.delete("/models/{model_id}", status_code=204)
async def delete_registry_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a registered model."""
    deleted = await registry_service.delete_model(session, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found")


@router.get("/models/{model_id}/config")
async def get_model_decrypted_config(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Return the full model config with decrypted API key.  Internal use only."""
    config = await registry_service.get_decrypted_config(session, model_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return config


# ---------------------------------------------------------------------------
# Test connection - LLM
# ---------------------------------------------------------------------------


def _is_image_model(model_name: str) -> bool:
    """Check if a model name indicates an image generation model."""
    m = (model_name or "").lower()
    return any(kw in m for kw in ("dall-e", "dalle", "image-gen", "nano-banana", "gemini-image", "flash-image"))


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_model_connection(
    body: TestConnectionRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Build the provider, send a simple message, and report success/failure.

    For image generation models (dall-e, etc.), tests the images endpoint
    instead of chat completions.
    """
    try:
        provider_config: dict = body.provider_config or {}
        if body.api_key:
            provider_config["api_key"] = body.api_key
        if body.base_url:
            provider_config["base_url"] = body.base_url
            if body.provider == "azure":
                provider_config.setdefault("azure_endpoint", body.base_url)

        # Image generation models: test with a lightweight images API call
        if _is_image_model(body.model_name):
            return await _test_image_model_connection(body, provider_config)

        # Chat/LLM models: test with a simple chat completion
        provider = get_provider(body.provider)
        model = provider.build_model(
            model=body.model_name,
            provider_config=provider_config,
            max_tokens=50,
            streaming=False,
        )
        messages = provider.build_messages([{"role": "user", "content": "Hello"}])

        start = time.perf_counter()
        ai_message = await provider.invoke(model, messages)
        latency_ms = (time.perf_counter() - start) * 1000

        content = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        return TestConnectionResponse(
            success=True,
            message=f"Model responded: {content[:100]}",
            latency_ms=round(latency_ms, 1),
        )
    except Exception as e:
        logger.warning("Test connection failed for %s/%s: %s", body.provider, body.model_name, e)
        return TestConnectionResponse(success=False, message=str(e))


async def _test_image_model_connection(body: TestConnectionRequest, provider_config: dict) -> TestConnectionResponse:
    """Test connection for image generation models.

    Routes to the correct test based on provider and model name:
    - Google: Vertex AI generateContent endpoint
    - Azure/OpenAI DALL-E: Official OpenAI Python SDK (matches MiBuddy behavior)
    - Others: generic httpx fallback
    """
    if body.provider in ("google", "google_vertex", "google_genai_vertex"):
        return await _test_vertex_image_connection(body, provider_config)

    # DALL-E specific: use the OpenAI Python SDK for reliability (matches MiBuddy)
    model_lower = (body.model_name or "").lower()
    if "dall-e" in model_lower or "dalle" in model_lower:
        return await _test_dalle_via_sdk(body, provider_config)

    # Fallback: generic httpx test (kept for non-DALL-E OpenAI-compatible image models)
    return await _test_dalle_connection(body, provider_config)


async def _test_dalle_via_sdk(body: TestConnectionRequest, provider_config: dict) -> TestConnectionResponse:
    """Test DALL-E using the OpenAI Python SDK (both Azure and OpenAI).

    Uses the same approach MiBuddy uses:
      AzureOpenAI(...).images.generate(model=deployment, prompt=..., response_format="b64_json")

    This is more reliable than raw httpx because the SDK handles:
      - Deployment name resolution for Azure
      - Authentication headers
      - Response format negotiation
      - Version/compatibility quirks
    """
    import asyncio
    try:
        from openai import AzureOpenAI, OpenAI
    except ImportError:
        return TestConnectionResponse(success=False, message="openai SDK not installed")

    api_key = provider_config.get("api_key", "")
    base_url = provider_config.get("base_url", "")
    model_name = body.model_name

    try:
        def _call():
            if body.provider == "azure":
                endpoint = base_url or provider_config.get("azure_endpoint", "")
                deployment = provider_config.get("azure_deployment", model_name)
                api_version = provider_config.get("api_version", "2024-12-01-preview")
                if not endpoint:
                    raise ValueError("Azure DALL-E model missing base_url / azure_endpoint")
                client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=endpoint,
                    timeout=60.0,
                )
                return client.images.generate(
                    model=deployment,
                    prompt="a small red circle on white background",
                    size="1024x1024",
                    response_format="b64_json",
                )
            else:
                # OpenAI public API or compatible
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url or None,
                    timeout=60.0,
                )
                return client.images.generate(
                    model=model_name,
                    prompt="a small red circle on white background",
                    size="1024x1024",
                    response_format="b64_json",
                )

        start = time.perf_counter()
        result = await asyncio.to_thread(_call)
        latency_ms = (time.perf_counter() - start) * 1000

        # Confirm we got an image back
        has_image = bool(result.data and len(result.data) > 0)
        if not has_image:
            return TestConnectionResponse(success=False, message="Image endpoint returned no data.")

        return TestConnectionResponse(
            success=True,
            message=f"DALL-E model '{model_name}' connected successfully.",
            latency_ms=round(latency_ms, 1),
        )
    except Exception as e:
        # Extract clean error message from OpenAI SDK exception body when possible
        error_msg = str(e)
        body_attr = getattr(e, "body", None)
        if isinstance(body_attr, dict):
            inner = body_attr.get("error", {})
            if isinstance(inner, dict) and inner.get("message"):
                error_msg = inner["message"]
        elif hasattr(e, "response") and hasattr(e.response, "json"):
            try:
                error_msg = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                pass
        logger.warning("DALL-E SDK test failed for %s/%s: %s", body.provider, model_name, error_msg)
        return TestConnectionResponse(success=False, message=error_msg)


async def _test_dalle_connection(body: TestConnectionRequest, provider_config: dict) -> TestConnectionResponse:
    """Test DALL-E connection (OpenAI or Azure)."""
    import httpx

    api_key = provider_config.get("api_key", "")
    base_url = provider_config.get("base_url", "")
    model_name = body.model_name

    try:
        if body.provider == "azure":
            endpoint = base_url or provider_config.get("azure_endpoint", "")
            deployment = provider_config.get("azure_deployment", model_name)
            api_version = provider_config.get("api_version", "2024-12-01-preview")
            url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/images/generations?api-version={api_version}"
            headers = {"api-key": api_key, "Content-Type": "application/json"}
        else:
            url = f"{(base_url or 'https://api.openai.com').rstrip('/')}/v1/images/generations"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        payload = {
            "model": model_name,
            "prompt": "test",
            "size": "1024x1024",
            "n": 1,
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        latency_ms = (time.perf_counter() - start) * 1000

        return TestConnectionResponse(
            success=True,
            message=f"Image model '{model_name}' connected successfully.",
            latency_ms=round(latency_ms, 1),
        )
    except httpx.HTTPStatusError as e:
        error_msg = str(e)
        try:
            error_msg = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            pass
        logger.warning("DALL-E test failed for %s/%s: %s", body.provider, model_name, error_msg)
        return TestConnectionResponse(success=False, message=error_msg)
    except Exception as e:
        logger.warning("DALL-E test failed for %s/%s: %s", body.provider, model_name, e)
        return TestConnectionResponse(success=False, message=str(e))


async def _test_vertex_image_connection(body: TestConnectionRequest, provider_config: dict) -> TestConnectionResponse:
    """Test Google Vertex AI Gemini image model connection (Nano Banana).

    Uses the Vertex AI generateContent endpoint with service account auth.
    Does a lightweight text-only request (no actual image generation) to verify connectivity.
    """
    import asyncio
    import json as json_mod
    import os
    import tempfile

    model_name = body.model_name
    api_key_or_path = provider_config.get("api_key", "")
    project_id = provider_config.get("project_id", "")
    location = provider_config.get("location", "us-central1")

    if not project_id:
        return TestConnectionResponse(
            success=False,
            message="Missing provider_config.project_id. Set the Google Cloud project ID.",
        )

    if not api_key_or_path:
        return TestConnectionResponse(
            success=False,
            message="Missing api_key. Set the path to the service account JSON file or inline JSON content.",
        )

    temp_file = None
    sa_path = api_key_or_path

    try:
        # If api_key is inline JSON, write to temp file
        if api_key_or_path.strip().startswith("{"):
            sa_data = json_mod.loads(api_key_or_path)
            temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json_mod.dump(sa_data, temp_file)
            temp_file.close()
            sa_path = temp_file.name

        if not os.path.exists(sa_path):
            return TestConnectionResponse(
                success=False,
                message=f"Service account file not found: {sa_path}",
            )

        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        authed_session = AuthorizedSession(credentials)

        vertex_model = f"projects/{project_id}/locations/{location}/publishers/google/models/{model_name}"
        endpoint = f"https://{location}-aiplatform.googleapis.com/v1/{vertex_model}:generateContent"

        # Lightweight test: text-only request (no image generation)
        body_payload = {
            "contents": [{"role": "user", "parts": [{"text": "Say hello"}]}],
        }

        start = time.perf_counter()
        response = await asyncio.to_thread(authed_session.post, endpoint, json=body_payload, timeout=30)
        latency_ms = (time.perf_counter() - start) * 1000

        if response.ok:
            return TestConnectionResponse(
                success=True,
                message=f"Vertex AI image model '{model_name}' connected successfully.",
                latency_ms=round(latency_ms, 1),
            )
        else:
            error_text = response.text[:200]
            return TestConnectionResponse(
                success=False,
                message=f"Vertex AI returned {response.status_code}: {error_text}",
            )

    except ImportError:
        return TestConnectionResponse(
            success=False,
            message="Missing dependencies: google-auth. Install with: pip install google-auth",
        )
    except Exception as e:
        logger.warning("Vertex AI test failed for %s/%s: %s", body.provider, model_name, e)
        return TestConnectionResponse(success=False, message=str(e))
    finally:
        if temp_file:
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Test connection - Embeddings
# ---------------------------------------------------------------------------


@router.post("/test-embedding-connection", response_model=TestConnectionResponse)
async def test_embedding_connection(
    body: TestConnectionRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Build an embedding provider, embed a test string, and report success/failure + latency."""
    try:
        provider = get_provider(body.provider)
        provider_config: dict = body.provider_config or {}
        if body.api_key:
            provider_config["api_key"] = body.api_key
        if body.base_url:
            provider_config["base_url"] = body.base_url
            if body.provider == "azure":
                provider_config.setdefault("azure_endpoint", body.base_url)

        embeddings = provider.build_embeddings(
            model=body.model_name,
            provider_config=provider_config,
        )

        start = time.perf_counter()
        result = await embeddings.aembed_query("Hello")
        latency_ms = (time.perf_counter() - start) * 1000

        dim = len(result) if result else 0
        return TestConnectionResponse(
            success=True,
            message=f"Embedding generated: {dim} dimensions",
            latency_ms=round(latency_ms, 1),
        )
    except NotImplementedError as e:
        return TestConnectionResponse(success=False, message=str(e))
    except Exception as e:
        logger.warning("Test embedding connection failed for %s/%s: %s", body.provider, body.model_name, e)
        return TestConnectionResponse(success=False, message=str(e))
