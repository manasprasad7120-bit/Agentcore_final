"""Generic semantic search service.

Provides embedding lifecycle (upsert/delete) and vector search for any entity type
(projects, agents, models, etc.) using Pinecone as the vector store and OpenAI
text-embedding-3-small for embeddings.

All functions are safe to call as fire-and-forget background tasks — errors are
logged but never propagated.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from loguru import logger

# Simple in-memory cache for query embeddings to reduce Azure OpenAI calls.
# Caches the last 128 unique queries. Cleared on process restart.
_query_embedding_cache: dict[str, list[float]] = {}
_CACHE_MAX_SIZE = 128


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_settings():
    from agentcore.services.deps import get_settings_service

    return get_settings_service().settings


def _is_enabled() -> bool:
    try:
        return _get_settings().semantic_search_enabled
    except Exception:
        return False


def _index_name() -> str:
    return _get_settings().semantic_search_pinecone_index


def _embedding_dimensions() -> int:
    return _get_settings().semantic_search_embedding_dimensions


def build_embedding_text(
    name: str,
    description: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Build enriched text for embedding from entity fields."""
    parts = [name]
    if description:
        parts.append(description)
    if tags:
        parts.append(", ".join(tags))
    return " | ".join(parts)


def build_vector_id(entity_type: str, entity_id: str) -> str:
    """Build a deterministic Pinecone vector ID for an entity."""
    return f"{entity_type}_{entity_id}"


# ---------------------------------------------------------------------------
# Upsert embedding (create or update)
# ---------------------------------------------------------------------------


async def upsert_entity_embedding(
    entity_type: str,
    entity_id: str,
    name: str,
    description: str | None = None,
    tags: list[str] | None = None,
    org_id: str | None = None,
    dept_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Generate embedding for an entity and upsert it into Pinecone.

    Safe to call via ``asyncio.create_task`` — never raises.
    """
    if not _is_enabled():
        logger.info("[SEMANTIC] Semantic search disabled, skipping upsert for {}/{}", entity_type, entity_id)
        return

    try:
        from agentcore.services.ltm.embeddings import embed_single
        from agentcore.services.pinecone_service_client import async_ingest_via_service

        text = build_embedding_text(name, description, tags)
        logger.info("[SEMANTIC] Generating embedding for {}/{}: text='{}'", entity_type, entity_id, text[:100])

        embedding = await embed_single(text)
        if not embedding:
            logger.warning("[SEMANTIC] Empty embedding for {}/{}, skipping upsert", entity_type, entity_id)
            return

        vec_id = build_vector_id(entity_type, entity_id)
        metadata: dict[str, Any] = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "name": name,
        }
        if org_id:
            metadata["org_id"] = org_id
        if dept_id:
            metadata["dept_id"] = dept_id
        if user_id:
            metadata["user_id"] = user_id

        # Try upsert with one retry on failure
        for attempt in range(2):
            try:
                logger.info("[SEMANTIC] Upserting to Pinecone index={} namespace={} vec_id={} (attempt {})", _index_name(), entity_type, vec_id, attempt + 1)
                await async_ingest_via_service(
                    index_name=_index_name(),
                    namespace=entity_type,
                    text_key="content",
                    documents=[{"page_content": text, "metadata": metadata}],
                    embedding_vectors=[embedding],
                    vector_ids=[vec_id],
                    auto_create_index=True,
                    embedding_dimension=_embedding_dimensions(),
                )
                logger.info("[SEMANTIC] Successfully upserted embedding for {}/{}", entity_type, entity_id)
                return
            except Exception:
                if attempt == 0:
                    logger.warning("[SEMANTIC] Upsert attempt 1 failed for {}/{}, retrying in 2s", entity_type, entity_id, exc_info=True)
                    await asyncio.sleep(2)
                else:
                    raise

    except Exception:
        logger.warning("[SEMANTIC] Failed to upsert embedding for {}/{} after all attempts", entity_type, entity_id, exc_info=True)


# ---------------------------------------------------------------------------
# Delete embedding
# ---------------------------------------------------------------------------


async def delete_entity_embedding(entity_type: str, entity_id: str) -> None:
    """Delete a single entity's embedding from Pinecone.

    Safe to call via ``asyncio.create_task`` — never raises.
    """
    if not _is_enabled():
        return

    try:
        from agentcore.services.pinecone_service_client import async_delete_vectors_via_service

        vec_id = build_vector_id(entity_type, entity_id)
        logger.info("[SEMANTIC] Deleting embedding {}/{} vec_id={}", entity_type, entity_id, vec_id)
        await async_delete_vectors_via_service(
            index_name=_index_name(),
            namespace=entity_type,
            vector_ids=[vec_id],
        )
        logger.info("[SEMANTIC] Successfully deleted embedding for {}/{}", entity_type, entity_id)

    except Exception:
        logger.warning("[SEMANTIC] Failed to delete embedding for {}/{}", entity_type, entity_id, exc_info=True)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def semantic_search(
    entity_type: str,
    query: str,
    top_k: int = 20,
    metadata_filter: dict | None = None,
) -> list[dict]:
    """Perform semantic search and return ranked entity IDs with scores.

    Returns a list of dicts: ``[{"entity_id": str, "score": float, "name": str}, ...]``

    Note: This returns unfiltered results unless metadata_filter is provided.
    The API layer is responsible for applying role-based visibility filtering via DB queries.
    """
    from agentcore.services.ltm.embeddings import embed_single
    from agentcore.services.pinecone_service_client import async_search_via_service

    # Use cached embedding if available (avoids repeated Azure OpenAI calls)
    cache_key = query.strip().lower()
    embedding = _query_embedding_cache.get(cache_key)
    if not embedding:
        embedding = await embed_single(query)
        if not embedding:
            logger.warning("[SEMANTIC] Empty embedding for query, returning empty results")
            return []
        # Evict oldest if cache full
        if len(_query_embedding_cache) >= _CACHE_MAX_SIZE:
            oldest_key = next(iter(_query_embedding_cache))
            del _query_embedding_cache[oldest_key]
        _query_embedding_cache[cache_key] = embedding

    result = await async_search_via_service(
        index_name=_index_name(),
        namespace=entity_type,
        text_key="content",
        query=query,
        query_embedding=embedding,
        number_of_results=top_k,
        use_reranking=_get_settings().semantic_search_use_reranking,
        rerank_top_n=top_k,
        metadata_filter=metadata_filter,
    )

    min_score = _get_settings().semantic_search_min_score
    all_results = result.get("results", [])
    hits: list[dict] = []
    for item in all_results:
        score = item.get("score", 0.0)
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        entity_id = meta.get("entity_id", "")
        if score >= min_score:
            hits.append({"entity_id": entity_id, "score": score, "name": name})
            logger.info("[SEMANTIC] Result: name='{}' score={:.4f} entity_id='{}' | KEPT (>= {:.2f})", name, score, entity_id, min_score)
        else:
            logger.info("[SEMANTIC] Result: name='{}' score={:.4f} entity_id='{}' | FILTERED (< {:.2f})", name, score, entity_id, min_score)

    logger.info("[SEMANTIC] Search query='{}' entity_type='{}' | pinecone_returned={} after_threshold={} min_score={:.2f}", query, entity_type, len(all_results), len(hits), min_score)

    return hits


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


async def backfill_embeddings(
    entity_type: str,
    entities: list[dict],
) -> int:
    """Batch-embed and ingest a list of entities into Pinecone.

    Each entity dict must have: ``id``, ``name``, and optionally ``description``, ``tags``,
    ``org_id``, ``dept_id``.

    Returns the number of vectors upserted.
    """
    if not entities:
        return 0

    from agentcore.services.ltm.embeddings import embed_batch
    from agentcore.services.pinecone_service_client import ingest_via_service

    batch_size = 100
    total_upserted = 0

    for i in range(0, len(entities), batch_size):
        batch = entities[i : i + batch_size]

        texts = [
            build_embedding_text(e["name"], e.get("description"), e.get("tags"))
            for e in batch
        ]
        vec_ids = [build_vector_id(entity_type, str(e["id"])) for e in batch]
        documents = []
        for e in batch:
            meta: dict[str, Any] = {
                "entity_id": str(e["id"]),
                "entity_type": entity_type,
                "name": e["name"],
            }
            if e.get("org_id"):
                meta["org_id"] = str(e["org_id"])
            if e.get("dept_id"):
                meta["dept_id"] = str(e["dept_id"])
            documents.append({"page_content": texts[len(documents)], "metadata": meta})

        embeddings = await embed_batch(texts)
        if not embeddings or len(embeddings) != len(texts):
            logger.warning("[SEMANTIC] Batch embedding failed for {} batch {}, skipping", entity_type, i)
            continue

        try:
            result = ingest_via_service(
                index_name=_index_name(),
                namespace=entity_type,
                text_key="content",
                documents=documents,
                embedding_vectors=embeddings,
                vector_ids=vec_ids,
                auto_create_index=True,
                embedding_dimension=_embedding_dimensions(),
            )
            total_upserted += result.get("vectors_upserted", 0)
        except Exception:
            logger.warning("[SEMANTIC] Batch ingest failed for {} batch {}", entity_type, i, exc_info=True)

    logger.info("[SEMANTIC] Backfill complete for {}: {} vectors upserted", entity_type, total_upserted)
    return total_upserted
