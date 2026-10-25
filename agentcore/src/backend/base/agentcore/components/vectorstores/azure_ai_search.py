import time

import numpy as np
from langchain_core.vectorstores import VectorStore
from loguru import logger

from agentcore.base.vectorstores.model import LCVectorStoreNode, check_cached_vector_store
from agentcore.io import BoolInput, DropdownInput, HandleInput, IntInput, Output, QueryInput, StrInput
from agentcore.schema.data import Data
from agentcore.schema.message import Message
def _get_service():
    from agentcore.services.azure_ai_search_service_client import (
        ensure_index,
        ingest_documents,
        search_documents,
    )
    return ensure_index, ingest_documents, search_documents


class AzureAISearchVectorStoreNode(LCVectorStoreNode):
    display_name = "Azure AI Search"
    description = "Azure AI Search vector store with hybrid search, semantic reranking, captions and answers"
    name = "AzureAISearch"
    icon = "Azure"
    documentation = ""
    inputs = [
        StrInput(name="index_name", display_name="Index Name", required=True,
                 info="Name of the Azure AI Search index."),
        StrInput(name="text_key", display_name="Text Key", value="content", advanced=True,
                 info="Field name used for the document text content."),
        HandleInput(
            name="ingest_data", display_name="Ingest Data",
            input_types=["Data", "DataFrame"], is_list=True,
        ),
        QueryInput(
            name="search_query", display_name="Search Query",
            info="Enter a query to run a similarity search.",
            placeholder="Enter a query...", tool_mode=True,
        ),
        HandleInput(name="embedding", display_name="Embedding", input_types=["Embeddings"]),
        BoolInput(name="auto_create_index", display_name="Auto Create Index", value=True,
                  advanced=True, info="Automatically create the index if it does not exist."),
        IntInput(name="embedding_dimension", display_name="Embedding Dimension", value=768, advanced=True),
        DropdownInput(name="search_mode", display_name="Search Mode",
                      options=["hybrid", "semantic"], value="hybrid", advanced=True,
                      info="hybrid = vector + full-text BM25, "
                           "semantic = hybrid + Azure semantic reranker"),
        StrInput(name="semantic_config_name", display_name="Semantic Config Name", value="",
                 advanced=True, info="Name of the semantic configuration on the index. "
                                    "Required when search mode is 'semantic'."),
        IntInput(name="number_of_results", display_name="Number of Results", value=4, advanced=True),
    ]

    outputs = [
        Output(
            display_name="Search Results",
            name="search_results",
            method="search_documents",
        ),
        Output(display_name="DataFrame", name="dataframe", method="as_dataframe"),
    ]

    # Cache the last search result so multiple outputs share the same query
    _last_search_result: dict | None = None

    def _resolve_search_query(self) -> str:
        query = self.search_query
        if query is None:
            return ""
        if isinstance(query, str):
            return query.strip()
        if isinstance(query, Message):
            return (query.text or "").strip()
        if isinstance(query, Data):
            return (query.text or "").strip()
        if isinstance(query, dict):
            return (query.get("text", "") or "").strip()
        return str(query).strip()

    def _ensure_index_exists(self):
        if not self.auto_create_index:
            logger.info(f"[AzureAISearch] Auto-create disabled, assuming index '{self.index_name}' exists")
            return
        logger.info(f"[AzureAISearch] Ensuring index '{self.index_name}' via SDK...")
        semantic_cfg = self.semantic_config_name or ""
        if self.search_mode == "semantic" and not semantic_cfg:
            semantic_cfg = f"{self.index_name}-semantic-config"
        ensure_index, _, _ = _get_service()
        result = ensure_index(
            index_name=self.index_name,
            embedding_dimension=self.embedding_dimension,
            similarity_metric="cosine",
            text_key=self.text_key,
            semantic_config_name=semantic_cfg,
        )
        if result.get("created"):
            logger.info(f"[AzureAISearch] Index '{self.index_name}' created")
        else:
            logger.info(f"[AzureAISearch] Index '{self.index_name}' already exists")

    def _get_embedding_model(self):
        emb = self.embedding
        if hasattr(emb, "embed_documents") and hasattr(emb, "embed_query"):
            return emb
        raise ValueError(
            "No valid embedding model provided. Please connect an Embedding component "
            "that implements embed_documents() and embed_query()."
        )

    def _detect_embedding_dimension(self, embedder) -> int:
        """Probe the embedding model to get the actual dimension and auto-set it."""
        try:
            probe = embedder.embed_query("dimension probe")
            actual_dim = len(probe)
        except Exception as e:
            logger.warning(f"[AzureAISearch] Could not probe embedding dimension: {e}, using configured value")
            return int(self.embedding_dimension)

        configured_dim = int(self.embedding_dimension)
        if actual_dim != configured_dim:
            logger.info(
                f"[AzureAISearch] Auto-correcting embedding dimension: "
                f"configured={configured_dim}, detected={actual_dim} from embedding model"
            )
            self.embedding_dimension = actual_dim

        logger.info(f"[AzureAISearch] Embedding dimension: {actual_dim}")
        return actual_dim

    def _ingest_documents(self, documents, embedder):
        texts = [doc.page_content for doc in documents]
        logger.info(f"[AzureAISearch] Generating embeddings for {len(texts)} chunk(s)...")
        t0 = time.time()
        dense_embeddings = embedder.embed_documents(texts)
        logger.info(f"[AzureAISearch] Embeddings done in {time.time()-t0:.1f}s")

        doc_items = [
            {"page_content": doc.page_content, "metadata": dict(doc.metadata) if doc.metadata else {}}
            for doc in documents
        ]

        _, ingest_documents, _ = _get_service()
        logger.info(f"[AzureAISearch] Ingesting {len(doc_items)} document(s)...")
        result = ingest_documents(
            index_name=self.index_name,
            text_key=self.text_key,
            documents=doc_items,
            embedding_vectors=dense_embeddings,
        )
        count = result.get("documents_indexed", 0)
        logger.info(f"[AzureAISearch] SDK indexed {count} documents")
        return count

    def _ingest_if_needed(self, wrapped_embeddings):
        self.ingest_data = self._prepare_ingest_data()
        if not self.ingest_data:
            return 0
        from langchain_core.documents import Document as LCDocument
        documents = []
        for doc in self.ingest_data:
            if isinstance(doc, Data):
                documents.append(doc.to_lc_document())
            elif isinstance(doc, LCDocument):
                documents.append(doc)
            elif isinstance(doc, str):
                documents.append(LCDocument(page_content=doc))
            elif isinstance(doc, dict):
                text = doc.get("text", doc.get("page_content", ""))
                metadata = {k: v for k, v in doc.items() if k not in ("text", "page_content")}
                documents.append(LCDocument(page_content=str(text), metadata=metadata))
            else:
                documents.append(LCDocument(page_content=str(doc)))
        if not documents:
            return 0
        return self._ingest_documents(documents, wrapped_embeddings)

    def _execute_search(self) -> dict:
        """Run the search and cache the raw result for use by multiple outputs."""
        if self._last_search_result is not None:
            return self._last_search_result

        query = self._resolve_search_query()

        real_embedding = self._get_embedding_model()
        wrapped = _Float32Embeddings(real_embedding)

        # Auto-detect dimension from embedding model BEFORE index creation
        self._detect_embedding_dimension(wrapped)

        try:
            self._ensure_index_exists()
        except Exception as e:
            raise ValueError(f"Error ensuring index: {e}") from e

        try:
            count = self._ingest_if_needed(wrapped)
            if count > 0:
                logger.info(f"[AzureAISearch] Ingested {count} document(s) into index={self.index_name!r}")
                time.sleep(1)
        except Exception as e:
            raise ValueError(f"Error ingesting: {e}") from e

        if not query:
            self._last_search_result = {"results": [], "answers": [], "_ingest_count": count, "_query": ""}
            return self._last_search_result

        query_embedding = wrapped.embed_query(query)

        is_semantic = self.search_mode == "semantic"
        semantic_cfg = self.semantic_config_name or ""
        if is_semantic and not semantic_cfg:
            semantic_cfg = f"{self.index_name}-semantic-config"

        _, _, search_documents = _get_service()
        try:
            result = search_documents(
                index_name=self.index_name,
                text_key=self.text_key,
                query=query,
                query_embedding=query_embedding,
                number_of_results=self.number_of_results,
                search_mode=self.search_mode,
                semantic_config_name=semantic_cfg,
                use_semantic_reranking=is_semantic,
                filter_expression="",
                include_captions=is_semantic,
                include_answers=is_semantic,
            )
        except Exception as e:
            # Fallback to hybrid if semantic search is not available on this service
            if is_semantic and "not enabled" in str(e).lower():
                logger.warning(
                    "[AzureAISearch] Semantic search not enabled on this service, falling back to hybrid"
                )
                result = search_documents(
                    index_name=self.index_name,
                    text_key=self.text_key,
                    query=query,
                    query_embedding=query_embedding,
                    number_of_results=self.number_of_results,
                    search_mode="hybrid",
                    semantic_config_name="",
                    use_semantic_reranking=False,
                    filter_expression="",
                    include_captions=False,
                    include_answers=False,
                )
            else:
                raise ValueError(f"Error searching: {type(e).__name__}: {e}") from e

        result["_ingest_count"] = count
        result["_query"] = query
        self._last_search_result = result
        return result

    @check_cached_vector_store
    def build_vector_store(self) -> VectorStore:
        real_embedding = self._get_embedding_model()
        wrapped = _Float32Embeddings(real_embedding)

        # Auto-detect dimension from embedding model BEFORE index creation
        self._detect_embedding_dimension(wrapped)

        try:
            self._ensure_index_exists()
        except Exception as e:
            raise ValueError(f"Error creating index: {e}") from e

        try:
            count = self._ingest_if_needed(wrapped)
            if count > 0:
                self.status = f"Ingested {count} document(s)"
        except Exception as e:
            raise ValueError(f"Error ingesting documents: {e}") from e

        return _AzureSearchProxy(
            index_name=self.index_name,
            text_key=self.text_key,
            embedding=wrapped,
            component=self,
        )

    def search_documents(self) -> list[Data]:
        result = self._execute_search()
        query = result.get("_query", "")
        count = result.get("_ingest_count", 0)

        if not query:
            self.status = f"Ingested {count} document(s). No search query provided."
            return []

        search_method = result.get("search_method", self.search_mode)
        rerank_info = result.get("rerank_info", "disabled")

        data = []
        for item in result.get("results", []):
            result_data = {
                "text": item["text"],
                "score": item.get("score", 0),
                "search_method": search_method,
                "reranking": rerank_info,
                "query": query,
                **(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
            }
            # Include semantic caption if available
            caption = item.get("caption")
            if caption:
                result_data["caption"] = caption
            caption_highlights = item.get("caption_highlights")
            if caption_highlights:
                result_data["caption_highlights"] = caption_highlights

            data.append(Data(text=item["text"], data=result_data))

        self.status = f"{len(data)} result(s) | mode={search_method} | rerank={rerank_info}"
        return data



class _Float32Embeddings:
    """Wrapper that ensures float32 output."""
    def __init__(self, real_model):
        self._model = real_model

    def embed_documents(self, texts):
        embeddings = self._model.embed_documents(texts)
        return [[float(np.float32(x)) for x in vec] for vec in embeddings]

    def embed_query(self, text):
        embedding = self._model.embed_query(text)
        return [float(np.float32(x)) for x in embedding]


class _AzureSearchProxy(VectorStore):
    """Lightweight VectorStore proxy that delegates all operations to Azure AI Search via SDK."""

    def __init__(self, index_name: str, text_key: str, embedding, component):
        self._index_name = index_name
        self._text_key = text_key
        self._embedding = embedding
        self._component = component

    @property
    def embeddings(self):
        return self._embedding

    def add_texts(self, texts, metadatas=None, **kwargs):
        from langchain_core.documents import Document as LCDocument
        docs = []
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            docs.append(LCDocument(page_content=text, metadata=meta))
        dense_embeddings = self._embedding.embed_documents(list(texts))
        doc_items = [
            {"page_content": doc.page_content, "metadata": dict(doc.metadata) if doc.metadata else {}}
            for doc in docs
        ]
        _, ingest_documents, _ = _get_service()
        result = ingest_documents(
            index_name=self._index_name,
            text_key=self._text_key,
            documents=doc_items,
            embedding_vectors=dense_embeddings,
        )
        return [str(i) for i in range(result.get("documents_indexed", 0))]

    def similarity_search(self, query, k=4, **kwargs):
        from langchain_core.documents import Document as LCDocument
        _, _, search_documents = _get_service()
        query_embedding = self._embedding.embed_query(query)
        result = search_documents(
            index_name=self._index_name,
            text_key=self._text_key,
            query=query,
            query_embedding=query_embedding,
            number_of_results=k,
        )
        docs = []
        for item in result.get("results", []):
            docs.append(LCDocument(
                page_content=item.get("text", ""),
                metadata=item.get("metadata", {}),
            ))
        return docs

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise NotImplementedError("Use the AzureAISearchVectorStoreNode component instead.")
