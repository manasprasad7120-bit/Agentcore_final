"""Core Pinecone operations — ingest, search, hybrid, rerank."""

from __future__ import annotations

import hashlib
import logging
import time

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_settings
from app.schemas import (
    CopyNamespaceRequest,
    CopyNamespaceResponse,
    DeleteIndexRequest,
    DeleteIndexResponse,
    DeleteNamespaceRequest,
    DeleteNamespaceResponse,
    DeleteVectorsRequest,
    DeleteVectorsResponse,
    DocumentItem,
    EnsureIndexRequest,
    EnsureIndexResponse,
    IndexInfo,
    IngestRequest,
    IngestResponse,
    ListIndexesResponse,
    NamespaceStatsRequest,
    NamespaceStatsResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    TestConnectionRequest,
    TestConnectionResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tenacity retry for transient Pinecone API failures
# ---------------------------------------------------------------------------

_pinecone_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
    before_sleep=lambda rs: logger.warning(
        "Pinecone retry attempt %d after %s", rs.attempt_number, rs.outcome.exception()
    ),
)

# ---------------------------------------------------------------------------
# Cached Pinecone client (singleton)
# ---------------------------------------------------------------------------

_pinecone_client = None


def _get_pinecone_client(api_key: str | None = None):
    """Return cached client for default key, or create a new one for custom keys."""
    global _pinecone_client
    from pinecone import Pinecone

    if api_key:
        # Custom key: always create fresh (used by test-connection)
        return Pinecone(api_key=api_key)

    if _pinecone_client is not None:
        return _pinecone_client

    key = get_settings().pinecone_api_key
    if not key:
        raise ValueError(
            "Pinecone API key not configured. "
            "Set PINECONE_API_KEY or PINECONE_SERVICE_PINECONE_API_KEY in .env."
        )
    _pinecone_client = Pinecone(api_key=key)
    logger.info("Pinecone client initialised")
    return _pinecone_client


def _stable_doc_id(namespace: str, index: int, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{namespace or 'ns'}_{index}_{digest}"


# ---------------------------------------------------------------------------
# Ensure index
# ---------------------------------------------------------------------------


@_pinecone_retry
def ensure_index(req: EnsureIndexRequest) -> EnsureIndexResponse:
    pc = _get_pinecone_client()
    existing = pc.list_indexes()
    names = [idx.name for idx in existing] if existing else []

    if req.index_name in names:
        return EnsureIndexResponse(exists=True, created=False, index_name=req.index_name)

    from pinecone import ServerlessSpec

    pc.create_index(
        name=req.index_name,
        dimension=req.embedding_dimension,
        metric="dotproduct",
        vector_type="dense",
        spec=ServerlessSpec(cloud=req.cloud_provider, region=req.cloud_region),
    )
    for attempt in range(30):
        try:
            desc = pc.describe_index(req.index_name)
            if desc.status and desc.status.get("ready", False):
                logger.info("Index '%s' ready after %ds", req.index_name, (attempt + 1) * 2)
                break
        except Exception as e:
            logger.debug("Index readiness check attempt %d failed: %s", attempt + 1, e)
        time.sleep(2)

    return EnsureIndexResponse(exists=True, created=True, index_name=req.index_name)


# ---------------------------------------------------------------------------
# Sparse vector generation
# ---------------------------------------------------------------------------


def _generate_sparse_vectors(pc, texts: list[str], sparse_model: str, input_type: str = "passage") -> list[dict]:
    all_sparse = []
    batch_size = get_settings().sparse_batch_size
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = pc.inference.embed(
            model=sparse_model,
            inputs=batch,
            parameters={"input_type": input_type, "truncate": "END"},
        )
        for item in response:
            indices = getattr(item, "sparse_indices", None) or getattr(item, "indices", [])
            values = getattr(item, "sparse_values", None) or getattr(item, "values", [])
            all_sparse.append({"indices": list(indices), "values": list(values)})
    return all_sparse


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


@_pinecone_retry
def ingest_documents(req: IngestRequest) -> IngestResponse:
    pc = _get_pinecone_client()

    # Auto-create index if it doesn't exist
    if req.auto_create_index:
        try:
            existing = pc.list_indexes()
            names = [idx.name for idx in existing] if existing else []
            if req.index_name not in names:
                from pinecone import ServerlessSpec
                logger.info(f"Auto-creating Pinecone index: {req.index_name} (dim={req.embedding_dimension})")
                pc.create_index(
                    name=req.index_name,
                    dimension=req.embedding_dimension,
                    metric="cosine",
                    spec=ServerlessSpec(cloud=req.cloud_provider, region=req.cloud_region),
                )
                # Wait for index to be ready
                import time
                for _ in range(30):
                    desc = pc.describe_index(req.index_name)
                    if desc.status and desc.status.get("ready", False):
                        break
                    time.sleep(2)
                logger.info(f"Pinecone index {req.index_name} created and ready")
        except Exception as e:
            logger.error(f"Failed to auto-create index {req.index_name}: {e}")

    index = pc.Index(req.index_name)
    settings = get_settings()

    texts = [doc.page_content for doc in req.documents]

    # Sparse vectors (optional)
    sparse_vectors = None
    if req.use_hybrid_search:
        try:
            sparse_vectors = _generate_sparse_vectors(pc, texts, req.sparse_model, input_type="passage")
        except Exception as e:
            logger.warning("Sparse embedding failed, ingesting dense-only: %s", e)

    # Build vector records
    vectors = []
    for i, (doc, dense) in enumerate(zip(req.documents, req.embedding_vectors)):
        metadata = dict(doc.metadata) if doc.metadata else {}
        metadata[req.text_key] = doc.page_content[:40000]
        vec_id = (
            req.vector_ids[i]
            if req.vector_ids and i < len(req.vector_ids)
            else _stable_doc_id(req.namespace, i, doc.page_content)
        )

        vec_data: dict = {"id": vec_id, "values": dense, "metadata": metadata}
        if sparse_vectors and i < len(sparse_vectors):
            vec_data["sparse_values"] = sparse_vectors[i]
        vectors.append(vec_data)

    # Batch upsert
    batch_size = settings.ingest_batch_size
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=req.namespace or "")

    return IngestResponse(
        vectors_upserted=len(vectors),
        index_name=req.index_name,
        namespace=req.namespace,
    )


# ---------------------------------------------------------------------------
# Hybrid score normalization
# ---------------------------------------------------------------------------


def _hybrid_score_norm(dense: list[float], sparse: dict, alpha: float):
    return (
        [v * alpha for v in dense],
        {"indices": sparse["indices"], "values": [v * (1 - alpha) for v in sparse["values"]]},
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@_pinecone_retry
def search_documents(req: SearchRequest) -> SearchResponse:
    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)

    retrieve_k = req.number_of_results
    if req.use_reranking:
        retrieve_k = max(req.number_of_results, 20)

    search_method = "dense"

    if req.use_hybrid_search:
        docs, scores = _hybrid_search(pc, index, req, retrieve_k)
        search_method = f"hybrid (alpha={req.hybrid_alpha})"
    else:
        docs, scores = _dense_search(index, req, retrieve_k)
        search_method = "dense"

    # Reranking
    rerank_info = "disabled"
    if req.use_reranking and docs:
        try:
            docs, scores = _rerank_documents(pc, req.query, docs, req.rerank_model, req.rerank_top_n)
            rerank_info = f"{req.rerank_model} (top {len(docs)})"
        except Exception as e:
            rerank_info = "failed"
            logger.warning("Reranking failed: %s", e)

    # Build results
    results = []
    for rank, (doc, score_info) in enumerate(zip(docs, scores)):
        results.append(SearchResultItem(
            text=doc["text"],
            metadata=doc["metadata"],
            score=score_info.get("score", score_info.get("rerank_score", 0.0)),
            score_info=score_info,
            rank=rank + 1,
        ))

    return SearchResponse(results=results, search_method=search_method, rerank_info=rerank_info)


def _dense_search(index, req: SearchRequest, k: int):
    query_kwargs = {
        "namespace": req.namespace or "",
        "top_k": k,
        "vector": req.query_embedding,
        "include_metadata": True,
    }
    if req.metadata_filter:
        query_kwargs["filter"] = req.metadata_filter
    results = index.query(**query_kwargs)
    docs = []
    scores = []
    for match in results.get("matches", []):
        metadata = match.get("metadata", {})
        text = metadata.pop(req.text_key, "")
        score = match.get("score", 0.0)
        docs.append({"text": text, "metadata": metadata})
        scores.append({"score": round(score, 4), "type": "dense"})
    return docs, scores


def _hybrid_search(pc, index, req: SearchRequest, k: int):
    sparse_vector = _generate_sparse_vectors(pc, [req.query], req.sparse_model, input_type="query")
    sparse = sparse_vector[0] if sparse_vector else {"indices": [], "values": []}

    alpha = max(0.0, min(req.hybrid_alpha, 1.0))
    hdense, hsparse = _hybrid_score_norm(req.query_embedding, sparse, alpha)

    query_kwargs = {
        "namespace": req.namespace or "",
        "top_k": k,
        "vector": hdense,
        "sparse_vector": hsparse,
        "include_metadata": True,
    }
    if req.metadata_filter:
        query_kwargs["filter"] = req.metadata_filter
    results = index.query(**query_kwargs)

    docs = []
    scores = []
    for match in results.get("matches", []):
        metadata = match.get("metadata", {})
        text = metadata.pop(req.text_key, "")
        score = match.get("score", 0.0)
        docs.append({"text": text, "metadata": metadata})
        scores.append({"score": round(score, 4), "type": "hybrid", "alpha": alpha})
    return docs, scores


def _rerank_documents(pc, query: str, docs: list[dict], rerank_model: str, top_n: int):
    rerank_input = [
        {"id": str(i), "text": doc["text"]}
        for i, doc in enumerate(docs)
    ][:100]

    response = pc.inference.rerank(
        model=rerank_model,
        query=query,
        documents=rerank_input,
        top_n=min(top_n, len(rerank_input)),
        return_documents=True,
        parameters={"truncate": "END"},
    )

    reranked_docs = []
    rerank_scores = []
    for rank, r in enumerate(response.data):
        if r.index < len(docs):
            reranked_docs.append(docs[r.index])
            rerank_scores.append({
                "rerank_score": round(r.score, 4),
                "rerank_position": rank + 1,
                "rerank_model": rerank_model,
                "type": "reranked",
            })
    return reranked_docs, rerank_scores


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


def test_connection(req: TestConnectionRequest) -> TestConnectionResponse:
    try:
        pc = _get_pinecone_client(api_key=req.pinecone_api_key)
        existing = pc.list_indexes()
        names = [idx.name for idx in existing] if existing else []
        return TestConnectionResponse(
            success=True,
            message=f"Connected. {len(names)} index(es) found.",
            indexes=names,
        )
    except Exception as e:
        logger.warning("Pinecone test-connection failed: %s", e)
        return TestConnectionResponse(success=False, message=str(e))


# ---------------------------------------------------------------------------
# Copy namespace (UAT → PROD migration)
# ---------------------------------------------------------------------------


def _delete_namespace_vectors(index, namespace: str) -> None:
    """Best-effort cleanup: delete all vectors in a namespace for rollback."""
    try:
        index.delete(delete_all=True, namespace=namespace)
        logger.info("[COPY_NS_ROLLBACK] Deleted all vectors in namespace '%s'", namespace)
    except Exception as cleanup_err:
        logger.error("[COPY_NS_ROLLBACK] Failed to clean up namespace '%s': %s", namespace, cleanup_err)


def copy_namespace(req: CopyNamespaceRequest) -> CopyNamespaceResponse:
    """Copy all vectors from source_namespace to target_namespace within the same index.

    Uses Pinecone's list → fetch → upsert pattern to migrate data between
    namespaces (e.g. UAT → PROD).

    Safety features:
    - Validates source namespace is not empty before starting
    - Checks target namespace is empty to prevent duplicate data
    - Retries each batch up to 3 times on transient failures
    - Rolls back (deletes target namespace) on unrecoverable failure
    """
    if req.source_namespace == req.target_namespace:
        raise ValueError("source_namespace and target_namespace must be different")

    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)

    # Validate source namespace has vectors
    stats = index.describe_index_stats()
    ns_map = stats.get("namespaces", {})
    source_info = ns_map.get(req.source_namespace, {})
    source_count = source_info.get("vector_count", 0)
    if source_count == 0:
        raise ValueError(
            f"Source namespace '{req.source_namespace}' is empty or does not exist in index '{req.index_name}'"
        )

    # Check target namespace is empty to prevent accidental duplicate data
    target_info = ns_map.get(req.target_namespace, {})
    target_count = target_info.get("vector_count", 0)
    if target_count > 0:
        raise ValueError(
            f"Target namespace '{req.target_namespace}' already has {target_count} vectors. "
            f"Delete it first or choose a different target namespace."
        )

    total_copied = 0
    max_retries = 3

    logger.info(
        "[COPY_NS_START] index=%s src=%s dst=%s batch=%d source_vectors=%d",
        req.index_name, req.source_namespace, req.target_namespace, req.batch_size, source_count,
    )

    try:
        # Pinecone SDK v8: index.list() is a generator that yields lists of
        # string IDs per page, handling pagination automatically.
        for vector_ids in index.list(
            namespace=req.source_namespace,
            limit=req.batch_size,
        ):
            if not vector_ids:
                continue

            fetch_response = index.fetch(ids=vector_ids, namespace=req.source_namespace)

            vectors_to_upsert = []
            for vid, vdata in fetch_response.vectors.items():
                vec: dict = {"id": vid, "values": vdata.values, "metadata": vdata.metadata or {}}
                if getattr(vdata, "sparse_values", None):
                    vec["sparse_values"] = {
                        "indices": list(vdata.sparse_values.indices),
                        "values": list(vdata.sparse_values.values),
                    }
                vectors_to_upsert.append(vec)

            if vectors_to_upsert:
                # Retry upsert up to max_retries times on transient failures
                last_err = None
                for attempt in range(1, max_retries + 1):
                    try:
                        index.upsert(vectors=vectors_to_upsert, namespace=req.target_namespace)
                        last_err = None
                        break
                    except Exception as upsert_err:
                        last_err = upsert_err
                        logger.warning(
                            "[COPY_NS_RETRY] Upsert attempt %d/%d failed: %s",
                            attempt, max_retries, upsert_err,
                        )
                        if attempt < max_retries:
                            time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s

                if last_err is not None:
                    raise RuntimeError(
                        f"Upsert failed after {max_retries} attempts at batch offset {total_copied}: {last_err}"
                    ) from last_err

                total_copied += len(vectors_to_upsert)
                logger.info("[COPY_NS_BATCH] copied=%d total=%d", len(vectors_to_upsert), total_copied)

    except Exception as copy_err:
        logger.error(
            "[COPY_NS_FAILED] index=%s dst=%s total_copied_before_fail=%d error=%s",
            req.index_name, req.target_namespace, total_copied, copy_err,
        )
        # Rollback: delete partially copied vectors from target namespace
        _delete_namespace_vectors(index, req.target_namespace)
        raise

    logger.info(
        "[COPY_NS_DONE] index=%s src=%s dst=%s total_copied=%d",
        req.index_name, req.source_namespace, req.target_namespace, total_copied,
    )
    return CopyNamespaceResponse(
        success=True,
        copied_vectors=total_copied,
        index_name=req.index_name,
        source_namespace=req.source_namespace,
        target_namespace=req.target_namespace,
        message=f"Copied {total_copied} vectors from '{req.source_namespace}' to '{req.target_namespace}'",
    )


# ---------------------------------------------------------------------------
# Namespace stats (observability)
# ---------------------------------------------------------------------------


@_pinecone_retry
def get_namespace_stats(req: NamespaceStatsRequest) -> NamespaceStatsResponse:
    """Return vector count and dimension for a specific namespace in an index."""
    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)
    stats = index.describe_index_stats()

    ns_map = stats.get("namespaces", {})
    ns_info = ns_map.get(req.namespace, {})

    return NamespaceStatsResponse(
        index_name=req.index_name,
        namespace=req.namespace,
        vector_count=ns_info.get("vector_count", 0),
        dimension=stats.get("dimension"),
    )


# ---------------------------------------------------------------------------
# List indexes (with namespace + vector counts)
# ---------------------------------------------------------------------------


@_pinecone_retry
def list_indexes() -> ListIndexesResponse:
    """List all Pinecone indexes with their namespaces and stats."""
    pc = _get_pinecone_client()
    existing = pc.list_indexes()
    indexes: list[IndexInfo] = []

    for idx in existing:
        name = idx.name if hasattr(idx, "name") else str(idx)
        info = IndexInfo(name=name)

        try:
            desc = pc.describe_index(name)
            info.dimension = getattr(desc, "dimension", None)
            info.metric = getattr(desc, "metric", "")
            info.host = getattr(desc, "host", "")
            status = getattr(desc, "status", None)
            if status:
                info.status = status.get("ready", False) and "ready" or "not_ready"
        except Exception as e:
            logger.warning("Failed to describe index '%s': %s", name, e)

        try:
            index = pc.Index(name)
            stats = index.describe_index_stats()
            info.vector_count = stats.get("total_vector_count", 0)
            ns_map = stats.get("namespaces", {})
            info.namespaces = list(ns_map.keys())
        except Exception as e:
            logger.warning("Failed to get stats for index '%s': %s", name, e)

        indexes.append(info)

    return ListIndexesResponse(indexes=indexes)


# ---------------------------------------------------------------------------
# Delete index
# ---------------------------------------------------------------------------


@_pinecone_retry
def delete_index(req: DeleteIndexRequest) -> DeleteIndexResponse:
    """Delete a Pinecone index entirely."""
    pc = _get_pinecone_client()
    try:
        pc.delete_index(req.index_name)
        logger.info("[DELETE_INDEX] Deleted index '%s'", req.index_name)
        return DeleteIndexResponse(
            success=True,
            index_name=req.index_name,
            message=f"Index '{req.index_name}' deleted successfully",
        )
    except Exception as e:
        logger.error("[DELETE_INDEX] Failed to delete index '%s': %s", req.index_name, e)
        raise


# ---------------------------------------------------------------------------
# Delete namespace (all vectors in a namespace)
# ---------------------------------------------------------------------------


@_pinecone_retry
def delete_namespace(req: DeleteNamespaceRequest) -> DeleteNamespaceResponse:
    """Delete all vectors in a namespace."""
    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)

    # Verify namespace exists
    stats = index.describe_index_stats()
    ns_map = stats.get("namespaces", {})
    if req.namespace not in ns_map:
        raise ValueError(f"Namespace '{req.namespace}' not found in index '{req.index_name}'")

    vector_count = ns_map[req.namespace].get("vector_count", 0)
    index.delete(delete_all=True, namespace=req.namespace)
    logger.info(
        "[DELETE_NS] Deleted namespace '%s' (%d vectors) from index '%s'",
        req.namespace, vector_count, req.index_name,
    )
    return DeleteNamespaceResponse(
        success=True,
        index_name=req.index_name,
        namespace=req.namespace,
        message=f"Deleted {vector_count} vectors from namespace '{req.namespace}'",
    )


# ---------------------------------------------------------------------------
# Delete specific vectors by ID
# ---------------------------------------------------------------------------


@_pinecone_retry
def delete_vectors(req: DeleteVectorsRequest) -> DeleteVectorsResponse:
    """Delete specific vectors by their IDs from a namespace."""
    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)

    index.delete(ids=req.vector_ids, namespace=req.namespace or "")
    logger.info(
        "[DELETE_VECTORS] Deleted %d vector(s) from namespace '%s' in index '%s'",
        len(req.vector_ids), req.namespace, req.index_name,
    )
    return DeleteVectorsResponse(
        success=True,
        index_name=req.index_name,
        namespace=req.namespace,
        deleted_count=len(req.vector_ids),
        message=f"Deleted {len(req.vector_ids)} vector(s) from namespace '{req.namespace}'",
    )
