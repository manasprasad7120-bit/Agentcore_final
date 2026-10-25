"""HTTP client for the Pinecone microservice.

Bridges agentcore backend to the standalone RAG microservice by
proxying index management, document ingestion, and search requests.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _get_pinecone_service_settings() -> tuple[str, str]:
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    # Prefer unified RAG_SERVICE_URL, fall back to legacy PINECONE_SERVICE_URL
    url = getattr(settings, "rag_service_url", "") or getattr(settings, "pinecone_service_url", "")
    api_key = getattr(settings, "rag_service_api_key", "") or getattr(settings, "pinecone_service_api_key", "")

    if not url:
        msg = "RAG_SERVICE_URL (or PINECONE_SERVICE_URL) is not configured. Set it in your environment or .env file."
        raise ValueError(msg)

    return url.rstrip("/"), api_key or ""


def _headers(api_key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def _raise_with_detail(resp: httpx.Response) -> None:
    """Raise an error that includes the actual detail message from the microservice."""
    if resp.is_success:
        return
    try:
        body = resp.json()
        detail = body.get("detail", resp.text)
    except Exception:
        detail = resp.text
    raise httpx.HTTPStatusError(
        message=detail,
        request=resp.request,
        response=resp,
    )


def is_service_configured() -> bool:
    try:
        _get_pinecone_service_settings()
        return True
    except (ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# Ensure index
# ---------------------------------------------------------------------------


def ensure_index_via_service(
    index_name: str,
    embedding_dimension: int = 768,
    cloud_provider: str = "aws",
    cloud_region: str = "us-east-1",
) -> dict:
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/ensure-index",
            headers=_headers(api_key),
            json={
                "index_name": index_name,
                "embedding_dimension": embedding_dimension,
                "cloud_provider": cloud_provider,
                "cloud_region": cloud_region,
            },
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Ingest documents
# ---------------------------------------------------------------------------


def ingest_via_service(
    index_name: str,
    namespace: str,
    text_key: str,
    documents: list[dict],
    embedding_vectors: list[list[float]],
    auto_create_index: bool = True,
    embedding_dimension: int = 768,
    cloud_provider: str = "aws",
    cloud_region: str = "us-east-1",
    use_hybrid_search: bool = False,
    sparse_model: str = "pinecone-sparse-english-v0",
    vector_ids: list[str] | None = None,
) -> dict:
    url, api_key = _get_pinecone_service_settings()
    body: dict = {
        "index_name": index_name,
        "namespace": namespace,
        "text_key": text_key,
        "documents": documents,
        "embedding_vectors": embedding_vectors,
        "auto_create_index": auto_create_index,
        "embedding_dimension": embedding_dimension,
        "cloud_provider": cloud_provider,
        "cloud_region": cloud_region,
        "use_hybrid_search": use_hybrid_search,
        "sparse_model": sparse_model,
    }
    if vector_ids is not None:
        body["vector_ids"] = vector_ids
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/ingest",
            headers=_headers(api_key),
            json=body,
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_via_service(
    index_name: str,
    namespace: str,
    text_key: str,
    query: str,
    query_embedding: list[float],
    number_of_results: int = 4,
    use_hybrid_search: bool = False,
    sparse_model: str = "pinecone-sparse-english-v0",
    hybrid_alpha: float = 0.7,
    use_reranking: bool = False,
    rerank_model: str = "pinecone-rerank-v0",
    rerank_top_n: int = 5,
) -> dict:
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/search",
            headers=_headers(api_key),
            json={
                "index_name": index_name,
                "namespace": namespace,
                "text_key": text_key,
                "query": query,
                "query_embedding": query_embedding,
                "number_of_results": number_of_results,
                "use_hybrid_search": use_hybrid_search,
                "sparse_model": sparse_model,
                "hybrid_alpha": hybrid_alpha,
                "use_reranking": use_reranking,
                "rerank_model": rerank_model,
                "rerank_top_n": rerank_top_n,
            },
        )
        _raise_with_detail(resp)
        return resp.json()


async def async_search_via_service(
    index_name: str,
    namespace: str,
    text_key: str,
    query: str,
    query_embedding: list[float],
    number_of_results: int = 4,
    use_reranking: bool = False,
    rerank_model: str = "pinecone-rerank-v0",
    rerank_top_n: int = 5,
    metadata_filter: dict | None = None,
) -> dict:
    """Async search — does NOT block the event loop."""
    url, api_key = _get_pinecone_service_settings()
    body = {
        "index_name": index_name,
        "namespace": namespace,
        "text_key": text_key,
        "query": query,
        "query_embedding": query_embedding,
        "number_of_results": number_of_results,
        "use_reranking": use_reranking,
        "rerank_model": rerank_model,
        "rerank_top_n": rerank_top_n,
    }
    if metadata_filter is not None:
        body["metadata_filter"] = metadata_filter
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{url}/v1/pinecone/search",
            headers=_headers(api_key),
            json=body,
        )
        _raise_with_detail(resp)
        return resp.json()


async def async_ingest_via_service(
    index_name: str,
    namespace: str,
    text_key: str,
    documents: list[dict],
    embedding_vectors: list[list[float]],
    vector_ids: list[str] | None = None,
    auto_create_index: bool = True,
    embedding_dimension: int = 768,
) -> dict:
    """Async ingest — does NOT block the event loop."""
    url, api_key = _get_pinecone_service_settings()
    body: dict = {
        "index_name": index_name,
        "namespace": namespace,
        "text_key": text_key,
        "documents": documents,
        "embedding_vectors": embedding_vectors,
        "auto_create_index": auto_create_index,
        "embedding_dimension": embedding_dimension,
    }
    if vector_ids is not None:
        body["vector_ids"] = vector_ids
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.post(
            f"{url}/v1/pinecone/ingest",
            headers=_headers(api_key),
            json=body,
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


def test_connection_via_service(pinecone_api_key: str | None = None) -> dict:
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/test-connection",
            headers=_headers(api_key),
            json={"pinecone_api_key": pinecone_api_key},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Copy namespace (UAT → PROD migration)
# ---------------------------------------------------------------------------


def copy_namespace_via_service(
    index_name: str,
    source_namespace: str,
    target_namespace: str,
    batch_size: int = 100,
) -> dict:
    """Copy all vectors from source to target namespace via pinecone-service (sync)."""
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/copy-namespace",
            headers=_headers(api_key),
            json={
                "index_name": index_name,
                "source_namespace": source_namespace,
                "target_namespace": target_namespace,
                "batch_size": batch_size,
            },
        )
        _raise_with_detail(resp)
        return resp.json()


async def async_copy_namespace_via_service(
    index_name: str,
    source_namespace: str,
    target_namespace: str,
    batch_size: int = 100,
) -> dict:
    """Copy all vectors from source to target namespace via pinecone-service (async).

    Uses httpx.AsyncClient so it does NOT block the event loop — safe to call
    from async FastAPI endpoints such as the approval hook.
    """
    url, api_key = _get_pinecone_service_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
        resp = await client.post(
            f"{url}/v1/pinecone/copy-namespace",
            headers=_headers(api_key),
            json={
                "index_name": index_name,
                "source_namespace": source_namespace,
                "target_namespace": target_namespace,
                "batch_size": batch_size,
            },
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Namespace stats (observability)
# ---------------------------------------------------------------------------


def namespace_stats_via_service(
    index_name: str,
    namespace: str = "",
) -> dict:
    """Get vector count and dimension for a namespace via pinecone-service."""
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/namespace-stats",
            headers=_headers(api_key),
            json={"index_name": index_name, "namespace": namespace},
        )
        _raise_with_detail(resp)
        return resp.json()


async def async_namespace_stats_via_service(
    index_name: str,
    namespace: str = "",
) -> dict:
    """Get vector count and dimension for a namespace via pinecone-service (async).

    Uses httpx.AsyncClient so it does NOT block the event loop — safe to call
    from async FastAPI endpoints such as the publish hook.
    """
    url, api_key = _get_pinecone_service_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{url}/v1/pinecone/namespace-stats",
            headers=_headers(api_key),
            json={"index_name": index_name, "namespace": namespace},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# List indexes
# ---------------------------------------------------------------------------


def list_indexes_via_service() -> dict:
    """List all Pinecone indexes with namespaces and stats."""
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(
            f"{url}/v1/pinecone/indexes",
            headers=_headers(api_key),
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Delete index
# ---------------------------------------------------------------------------


def delete_index_via_service(index_name: str) -> dict:
    """Delete a Pinecone index entirely via pinecone-service."""
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/delete-index",
            headers=_headers(api_key),
            json={"index_name": index_name},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Delete namespace
# ---------------------------------------------------------------------------


def delete_namespace_via_service(index_name: str, namespace: str) -> dict:
    """Delete all vectors in a namespace via pinecone-service."""
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/delete-namespace",
            headers=_headers(api_key),
            json={"index_name": index_name, "namespace": namespace},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Delete specific vectors by ID
# ---------------------------------------------------------------------------


def delete_vectors_via_service(index_name: str, namespace: str, vector_ids: list[str]) -> dict:
    """Delete specific vectors by ID via pinecone-service."""
    url, api_key = _get_pinecone_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{url}/v1/pinecone/delete-vectors",
            headers=_headers(api_key),
            json={"index_name": index_name, "namespace": namespace, "vector_ids": vector_ids},
        )
        _raise_with_detail(resp)
        return resp.json()


async def async_delete_vectors_via_service(index_name: str, namespace: str, vector_ids: list[str]) -> dict:
    """Delete specific vectors by ID via pinecone-service (async)."""
    url, api_key = _get_pinecone_service_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.post(
            f"{url}/v1/pinecone/delete-vectors",
            headers=_headers(api_key),
            json={"index_name": index_name, "namespace": namespace, "vector_ids": vector_ids},
        )
        _raise_with_detail(resp)
        return resp.json()
