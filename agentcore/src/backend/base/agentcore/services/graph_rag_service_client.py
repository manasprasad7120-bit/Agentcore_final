"""HTTP client for the Graph RAG microservice.

Bridges agentcore backend to the standalone RAG microservice by
proxying Neo4j entity ingestion, search, community detection, and stats.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Connection timeout: fail fast if service is unreachable (15s).
# Read/write timeout: None for long-running ops (ingest, copy, embeddings)
# so they run until completion without being cut off.
_CONNECT_TIMEOUT = 15.0

_TIMEOUT_LONG = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=None, write=None, pool=None)
_TIMEOUT_MEDIUM = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=120.0, write=60.0, pool=None)
_TIMEOUT_SHORT = httpx.Timeout(connect=_CONNECT_TIMEOUT, read=30.0, write=30.0, pool=None)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _get_graph_rag_service_settings() -> tuple[str, str]:
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    # Prefer unified RAG_SERVICE_URL, fall back to legacy GRAPH_RAG_SERVICE_URL
    url = getattr(settings, "rag_service_url", "") or getattr(settings, "graph_rag_service_url", "")
    api_key = getattr(settings, "rag_service_api_key", "") or getattr(settings, "graph_rag_service_api_key", "")

    if not url:
        msg = "RAG_SERVICE_URL (or GRAPH_RAG_SERVICE_URL) is not configured. Set it in your environment or .env file."
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


def _request(
    method: str,
    endpoint: str,
    payload: dict,
    timeout: httpx.Timeout,
    operation: str,
) -> dict:
    """Central request helper with proper error logging."""
    try:
        url, api_key = _get_graph_rag_service_settings()
    except ValueError as e:
        logger.error("[Graph RAG] %s failed: %s", operation, e)
        raise

    full_url = f"{url}{endpoint}"
    logger.info("[Graph RAG] %s → %s", operation, full_url)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, full_url, headers=_headers(api_key), json=payload)
            _raise_with_detail(resp)
            result = resp.json()
            logger.info("[Graph RAG] %s completed (HTTP %s)", operation, resp.status_code)
            return result
    except httpx.ConnectError as e:
        logger.error(
            "[Graph RAG] %s failed — cannot connect to service at %s. "
            "Is graph-rag-service running? Error: %s",
            operation, url, e,
        )
        raise ValueError(
            f"Graph RAG service is unreachable at {url}. "
            f"Please ensure graph-rag-service is running."
        ) from e
    except httpx.TimeoutException as e:
        logger.error(
            "[Graph RAG] %s timed out after connecting to %s. Error: %s",
            operation, url, e,
        )
        raise ValueError(
            f"Graph RAG service request timed out for {operation}. "
            f"The service may be overloaded or Neo4j may be unresponsive."
        ) from e
    except httpx.HTTPStatusError as e:
        logger.error(
            "[Graph RAG] %s returned HTTP %s: %s",
            operation, e.response.status_code, e.args[0] if e.args else "",
        )
        raise


def is_service_configured() -> bool:
    try:
        _get_graph_rag_service_settings()
        return True
    except (ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# Ingest entities (no read timeout — runs until completion)
# ---------------------------------------------------------------------------


def ingest_via_service(entities: list[dict], graph_kb_id: str = "default") -> dict:
    logger.info("[Graph RAG] Ingesting %d entities into graph '%s'", len(entities), graph_kb_id)
    return _request(
        "POST", "/v1/graph/ingest",
        {"entities": entities, "graph_kb_id": graph_kb_id},
        timeout=_TIMEOUT_LONG,
        operation=f"Ingest ({len(entities)} entities, kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Fetch unembedded entities
# ---------------------------------------------------------------------------


def fetch_unembedded_via_service(graph_kb_id: str = "default", batch_size: int = 200) -> dict:
    return _request(
        "POST", "/v1/graph/fetch-unembedded",
        {"graph_kb_id": graph_kb_id, "batch_size": batch_size},
        timeout=_TIMEOUT_MEDIUM,
        operation=f"Fetch unembedded (kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Store embeddings (no read timeout — batch can be large)
# ---------------------------------------------------------------------------


def store_embeddings_via_service(
    graph_kb_id: str,
    embeddings: list[dict],
) -> dict:
    logger.info("[Graph RAG] Storing %d embeddings for graph '%s'", len(embeddings), graph_kb_id)
    return _request(
        "POST", "/v1/graph/store-embeddings",
        {"graph_kb_id": graph_kb_id, "embeddings": embeddings},
        timeout=_TIMEOUT_LONG,
        operation=f"Store embeddings ({len(embeddings)} vectors, kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Ensure vector index
# ---------------------------------------------------------------------------


def ensure_vector_index_via_service(graph_kb_id: str = "default") -> dict:
    return _request(
        "POST", "/v1/graph/ensure-vector-index",
        {"graph_kb_id": graph_kb_id},
        timeout=_TIMEOUT_SHORT,
        operation=f"Ensure vector index (kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_via_service(
    query: str,
    query_embedding: list[float] | None = None,
    graph_kb_id: str = "default",
    search_type: str = "vector_similarity",
    number_of_results: int = 10,
    expansion_hops: int = 2,
    include_source_chunks: bool = True,
) -> dict:
    return _request(
        "POST", "/v1/graph/search",
        {
            "query": query,
            "query_embedding": query_embedding,
            "graph_kb_id": graph_kb_id,
            "search_type": search_type,
            "number_of_results": number_of_results,
            "expansion_hops": expansion_hops,
            "include_source_chunks": include_source_chunks,
        },
        timeout=_TIMEOUT_MEDIUM,
        operation=f"Search (query='{query[:50]}', kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def get_stats_via_service(graph_kb_id: str = "default") -> dict:
    return _request(
        "POST", "/v1/graph/stats",
        {"graph_kb_id": graph_kb_id},
        timeout=_TIMEOUT_SHORT,
        operation=f"Stats (kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Community detection (no read timeout — can be slow for large graphs)
# ---------------------------------------------------------------------------


def detect_communities_via_service(
    graph_kb_id: str = "default",
    max_communities: int = 10,
    min_community_size: int = 2,
) -> dict:
    return _request(
        "POST", "/v1/graph/communities/detect",
        {
            "graph_kb_id": graph_kb_id,
            "max_communities": max_communities,
            "min_community_size": min_community_size,
        },
        timeout=_TIMEOUT_LONG,
        operation=f"Detect communities (kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Store community summaries
# ---------------------------------------------------------------------------


def store_communities_via_service(
    graph_kb_id: str,
    communities: list[dict],
) -> dict:
    return _request(
        "POST", "/v1/graph/communities/store",
        {"graph_kb_id": graph_kb_id, "communities": communities},
        timeout=_TIMEOUT_MEDIUM,
        operation=f"Store communities ({len(communities)} communities, kb={graph_kb_id})",
    )


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


def test_connection_via_service(
    neo4j_uri: str | None = None,
    neo4j_username: str | None = None,
    neo4j_password: str | None = None,
    neo4j_database: str | None = None,
) -> dict:
    return _request(
        "POST", "/v1/graph/test-connection",
        {
            "neo4j_uri": neo4j_uri,
            "neo4j_username": neo4j_username,
            "neo4j_password": neo4j_password,
            "neo4j_database": neo4j_database,
        },
        timeout=_TIMEOUT_SHORT,
        operation="Test Neo4j connection",
    )


# ---------------------------------------------------------------------------
# Copy graph_kb (UAT → PROD migration — no read timeout)
# ---------------------------------------------------------------------------


def copy_graph_kb_via_service(
    source_graph_kb_id: str,
    target_graph_kb_id: str,
    batch_size: int = 200,
) -> dict:
    logger.info(
        "[Graph RAG] Copying graph KB '%s' → '%s' (batch_size=%d)",
        source_graph_kb_id, target_graph_kb_id, batch_size,
    )
    return _request(
        "POST", "/v1/graph/copy-graph-kb",
        {
            "source_graph_kb_id": source_graph_kb_id,
            "target_graph_kb_id": target_graph_kb_id,
            "batch_size": batch_size,
        },
        timeout=_TIMEOUT_LONG,
        operation=f"Copy graph KB ({source_graph_kb_id} → {target_graph_kb_id})",
    )
