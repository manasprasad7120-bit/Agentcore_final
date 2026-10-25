from __future__ import annotations

import logging
import uuid

from azure.core.credentials import TokenCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _get_settings() -> str:
    """Return endpoint from app settings."""
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    endpoint = getattr(settings, "azure_ai_search_endpoint", "")

    if not endpoint:
        raise ValueError(
            "AZURE_AI_SEARCH_ENDPOINT is not configured. "
            "Set it in your .env file."
        )
    return endpoint.rstrip("/")


def _credential() -> TokenCredential:
    from azure.identity import DefaultAzureCredential
    logger.info(
        "[AzureAISearch] Using DefaultAzureCredential — "
        "locally this resolves via 'az login', in production via Managed Identity."
    )
    try:
        credential = DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_interactive_browser_credential=True,
        )
        return credential
    except Exception as exc:
        logger.error(
            "[AzureAISearch] Failed to build DefaultAzureCredential: %s. "
            "Locally run 'az login' first. In production ensure a Managed Identity is assigned.",
            exc,
        )
        raise


def _index_client() -> SearchIndexClient:
    endpoint = _get_settings()
    try:
        client = SearchIndexClient(endpoint=endpoint, credential=_credential())
        logger.debug("[AzureAISearch] SearchIndexClient created for endpoint=%s", endpoint)
        return client
    except Exception as exc:
        logger.error(
            "[AzureAISearch] Could not create SearchIndexClient for endpoint=%s — %s",
            endpoint, exc,
        )
        raise


def _search_client(index_name: str) -> SearchClient:
    endpoint = _get_settings()
    try:
        client = SearchClient(endpoint=endpoint, index_name=index_name, credential=_credential())
        logger.debug(
            "[AzureAISearch] SearchClient created for endpoint=%s index=%s", endpoint, index_name
        )
        return client
    except Exception as exc:
        logger.error(
            "[AzureAISearch] Could not create SearchClient for endpoint=%s index=%s — %s",
            endpoint, index_name, exc,
        )
        raise


def is_service_configured() -> bool:
    try:
        _get_settings()
        return True
    except (ValueError, Exception):
        return False


# ===========================================================================
# INDEX MANAGEMENT
# ===========================================================================


def ensure_index(
    index_name: str,
    embedding_dimension: int = 768,
    similarity_metric: str = "cosine",
    text_key: str = "content",
    semantic_config_name: str = "",
) -> dict:
    """Create the index if it doesn't exist. Idempotent."""
    client = _index_client()

    # Check if index already exists
    try:
        existing = client.get_index(index_name)
        if existing:
            logger.info(f"[AzureAISearch] Index '{index_name}' already exists")
            return {"created": False, "index_name": index_name}
    except Exception:
        pass  # Index doesn't exist, create it

    # Vector search configuration
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(name="hnsw-config"),
        ],
        profiles=[
            VectorSearchProfile(
                name="vector-profile",
                algorithm_configuration_name="hnsw-config",
            ),
        ],
    )

    # Fields
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchableField(name=text_key, type=SearchFieldDataType.String),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=embedding_dimension,
            vector_search_profile_name="vector-profile",
        ),
        SimpleField(name="metadata", type=SearchFieldDataType.String, filterable=False),
    ]

    # Semantic configuration (optional)
    semantic_search = None
    if semantic_config_name:
        semantic_search = SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name=semantic_config_name,
                    prioritized_fields=SemanticPrioritizedFields(
                        content_fields=[SemanticField(field_name=text_key)],
                    ),
                ),
            ],
        )

    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )

    client.create_or_update_index(index)
    logger.info(f"[AzureAISearch] Index '{index_name}' created (dim={embedding_dimension})")
    return {"created": True, "index_name": index_name}


def delete_index(index_name: str) -> dict:
    """Delete an index."""
    client = _index_client()
    client.delete_index(index_name)
    logger.info(f"[AzureAISearch] Index '{index_name}' deleted")
    return {"deleted": True, "index_name": index_name}


# ===========================================================================
# DOCUMENT INGESTION
# ===========================================================================


def ingest_documents(
    index_name: str,
    text_key: str,
    documents: list[dict],
    embedding_vectors: list[list[float]],
) -> dict:
    """Upload documents with embeddings to the index.

    documents: list of {"page_content": "...", "metadata": {...}}
    embedding_vectors: parallel list of embedding vectors
    """
    client = _search_client(index_name)

    batch = []
    for i, (doc, vector) in enumerate(zip(documents, embedding_vectors)):
        doc_id = str(uuid.uuid4())
        metadata = doc.get("metadata", {})

        batch.append({
            "id": doc_id,
            text_key: doc.get("page_content", ""),
            "embedding": vector,
            "metadata": str(metadata) if metadata else "",
        })

    # Upload in batches of 1000 (Azure limit per request)
    total_uploaded = 0
    batch_size = 1000
    for start in range(0, len(batch), batch_size):
        chunk = batch[start : start + batch_size]
        result = client.upload_documents(documents=chunk)
        succeeded = sum(1 for r in result if r.succeeded)
        total_uploaded += succeeded
        if succeeded < len(chunk):
            failed = [r for r in result if not r.succeeded]
            logger.warning(
                f"[AzureAISearch] {len(failed)} document(s) failed to upload: "
                f"{failed[0].error_message if failed else 'unknown'}"
            )

    logger.info(f"[AzureAISearch] Uploaded {total_uploaded}/{len(batch)} documents to '{index_name}'")
    return {"documents_indexed": total_uploaded, "total": len(batch)}


# ===========================================================================
# SEARCH
# ===========================================================================


def search_documents(
    index_name: str,
    text_key: str,
    query: str,
    query_embedding: list[float],
    number_of_results: int = 4,
    search_mode: str = "vector",
    semantic_config_name: str = "",
    use_semantic_reranking: bool = False,
    filter_expression: str = "",
    include_captions: bool = False,
    include_answers: bool = False,
) -> dict:
    """Search the index.

    Returns: {
        "results": [{"text": ..., "score": ..., "metadata": ..., "caption": ..., "caption_highlights": ...}],
        "answers": [{"text": ..., "score": ..., "highlights": ..., "key": ...}],
        "search_method": ...,
        "rerank_info": ...,
    }
    """
    client = _search_client(index_name)

    # Vector query
    vector_query = VectorizedQuery(
        vector=query_embedding,
        k_nearest_neighbors=number_of_results,
        fields="embedding",
    )

    # Build search kwargs
    search_kwargs: dict = {
        "search_text": None,
        "vector_queries": [vector_query],
        "top": number_of_results,
        "select": [text_key, "metadata"],
    }

    # Hybrid: add full-text search
    if search_mode in ("hybrid", "semantic"):
        search_kwargs["search_text"] = query

    # OData filter
    if filter_expression:
        search_kwargs["filter"] = filter_expression

    # Semantic reranking
    if use_semantic_reranking and semantic_config_name:
        search_kwargs["query_type"] = "semantic"
        search_kwargs["semantic_configuration_name"] = semantic_config_name
        if include_captions:
            search_kwargs["query_caption"] = "extractive"
        if include_answers:
            search_kwargs["query_answer"] = "extractive"

    # Execute search
    response = client.search(**search_kwargs)

    # Parse results
    results = []
    for doc in response:
        item = {
            "text": doc.get(text_key, ""),
            "score": doc.get("@search.score", 0),
            "metadata": doc.get("metadata") or {},
        }

        # Reranker score (if semantic)
        reranker_score = doc.get("@search.reranker_score")
        if reranker_score is not None:
            item["reranker_score"] = reranker_score

        # Captions
        captions = doc.get("@search.captions")
        if captions:
            item["caption"] = captions[0].text if captions[0].text else ""
            item["caption_highlights"] = captions[0].highlights if captions[0].highlights else ""

        results.append(item)

    # Parse semantic answers
    answers = []
    if include_answers and hasattr(response, "get_answers"):
        try:
            raw_answers = response.get_answers() or []
            for ans in raw_answers:
                answers.append({
                    "text": ans.text or "",
                    "score": ans.score or 0,
                    "highlights": ans.highlights or "",
                    "key": ans.key or "",
                })
        except Exception as e:
            logger.warning(f"[AzureAISearch] Failed to parse semantic answers: {e}")

    search_method = search_mode
    rerank_info = "semantic" if use_semantic_reranking else "disabled"

    return {
        "results": results,
        "answers": answers,
        "search_method": search_method,
        "rerank_info": rerank_info,
    }


# ===========================================================================
# INDEX STATS
# ===========================================================================


def index_stats(index_name: str) -> dict:
    """Get document count for the index."""
    client = _search_client(index_name)
    count = client.get_document_count()
    return {"index_name": index_name, "document_count": count}