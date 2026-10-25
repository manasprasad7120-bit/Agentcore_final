"""Document processor service for orchestrator document Q&A.

Orchestrates the RAG pipeline:
  extract text → chunk → embed → ingest into Pinecone → search → build context

Uses existing agentcore infrastructure:
  - document_extractor.py for text extraction
  - ltm/embeddings.py for embedding generation
  - pinecone_service_client.py for vector store operations
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from loguru import logger


# ---------------------------------------------------------------------------
# Text chunking (simple recursive splitter)
# ---------------------------------------------------------------------------

def _chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks.

    Uses paragraph/sentence boundaries when possible.
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # Split on paragraph boundaries first
    separators = ["\n\n", "\n", ". ", " "]
    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Find the best split point near the end
        best_split = end
        for sep in separators:
            # Look backward from end for a separator
            idx = text.rfind(sep, start + chunk_size // 2, end)
            if idx > start:
                best_split = idx + len(sep)
                break

        chunk = text[start:best_split].strip()
        if chunk:
            chunks.append(chunk)

        # Move start with overlap
        start = best_split - chunk_overlap
        if start < 0:
            start = 0
        # Avoid infinite loop
        if start >= best_split:
            start = best_split

    return chunks


def _make_chunk_id(session_id: str, source_file: str, chunk_index: int, content: str) -> str:
    """Generate a deterministic chunk ID for idempotent ingestion."""
    raw = f"{session_id}:{source_file}:{chunk_index}:{content[:100]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _get_settings():
    from agentcore.services.deps import get_settings_service
    return get_settings_service().settings


# ---------------------------------------------------------------------------
# Ingest documents into Pinecone
# ---------------------------------------------------------------------------

async def process_and_ingest(
    file_paths: list[str],
    session_id: str,
) -> int:
    """Extract text from files, chunk, embed, and ingest into Pinecone.

    Args:
        file_paths: List of storage-relative file paths.
        session_id: Chat session ID (used as Pinecone namespace).

    Returns:
        Number of chunks ingested.
    """
    from agentcore.services.mibuddy.document_extractor import extract_text
    from agentcore.services.ltm.embeddings import embed_batch
    from agentcore.services.pinecone_service_client import async_ingest_via_service

    settings = _get_settings()
    index_name = settings.doc_qa_pinecone_index
    chunk_size = settings.doc_qa_chunk_size
    chunk_overlap = settings.doc_qa_chunk_overlap

    all_chunks: list[str] = []
    all_documents: list[dict] = []
    all_ids: list[str] = []

    for file_path in file_paths:
        file_name = Path(file_path).name
        logger.info(f"[DocQA] Extracting text from: {file_name}")

        text = await extract_text(file_path)
        if not text.strip() or text.startswith("[ERROR]") or text.startswith("[Unsupported"):
            logger.warning(f"[DocQA] Skipping {file_name}: {text[:100]}")
            continue

        chunks = _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        logger.info(f"[DocQA] {file_name}: {len(chunks)} chunks created")

        for i, chunk in enumerate(chunks):
            chunk_id = _make_chunk_id(session_id, file_name, i, chunk)
            all_chunks.append(chunk)
            # Nest the metadata under a "metadata" key so the Pinecone service
            # stores it as queryable metadata. Flat top-level keys (the old
            # shape) were silently dropped by the service, which is why
            # `item["metadata"]` came back empty on search.
            all_documents.append({
                "page_content": chunk,
                "metadata": {
                    "source_file": file_name,
                    "chunk_index": i,
                    "session_id": session_id,
                },
            })
            all_ids.append(chunk_id)

    if not all_chunks:
        logger.warning("[DocQA] No text extracted from any files")
        return 0

    # Generate embeddings in batches
    logger.info(f"[DocQA] Generating embeddings for {len(all_chunks)} chunks")
    batch_size = 50
    all_embeddings: list[list[float]] = []

    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i : i + batch_size]
        embeddings = await embed_batch(batch)
        if not embeddings:
            logger.error("[DocQA] Embedding generation failed — check LTM_EMBEDDING_API_KEY")
            return 0
        all_embeddings.extend(embeddings)

    if len(all_embeddings) != len(all_chunks):
        logger.error(f"[DocQA] Embedding count mismatch: {len(all_embeddings)} vs {len(all_chunks)}")
        return 0

    # Determine embedding dimension from first vector
    embedding_dim = len(all_embeddings[0]) if all_embeddings else 1536

    # Ingest into Pinecone
    logger.info(f"[DocQA] Ingesting {len(all_chunks)} chunks into Pinecone index={index_name} namespace={session_id}")
    try:
        result = await async_ingest_via_service(
            index_name=index_name,
            namespace=session_id,
            text_key="page_content",
            documents=all_documents,
            embedding_vectors=all_embeddings,
            auto_create_index=True,
            embedding_dimension=embedding_dim,
            vector_ids=all_ids,
        )
        count = result.get("upserted_count", len(all_chunks))
        logger.info(f"[DocQA] Successfully ingested {count} chunks")
        return count
    except Exception as e:
        logger.error(f"[DocQA] Pinecone ingestion failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Search documents in Pinecone
# ---------------------------------------------------------------------------

def _extract_match_text(match: dict) -> str:
    """Pull text out of a Pinecone match, handling the various shapes."""
    return (
        match.get("text", "")
        or match.get("metadata", {}).get("page_content", "")
        or match.get("metadata", {}).get("text", "")
    )


async def _discover_session_files(
    index_name: str,
    namespace: str,
    query_embedding: list[float],
    query: str,
) -> list[str]:
    """Best-effort discovery of which source files exist in this namespace.

    Used when the caller doesn't know which files were uploaded earlier in the
    session (e.g. follow-up questions after the initial upload). We issue one
    broad query and collect unique `source_file` values from the metadata.
    """
    from agentcore.services.pinecone_service_client import async_search_via_service

    try:
        result = await async_search_via_service(
            index_name=index_name,
            namespace=namespace,
            text_key="page_content",
            query=query,
            query_embedding=query_embedding,
            number_of_results=50,
        )
    except Exception as e:
        logger.warning(f"[DocQA] File discovery query failed: {e}")
        return []

    matches = result.get("results", []) or result.get("matches", [])
    files: list[str] = []
    seen: set[str] = set()
    for match in matches:
        source = match.get("metadata", {}).get("source_file") or match.get("source_file")
        if source and source not in seen:
            seen.add(source)
            files.append(source)
    return files


async def search_documents(
    query: str,
    session_id: str,
    top_k: int | None = None,
    file_list: list[str] | None = None,
) -> list[dict]:
    """Search Pinecone for relevant document chunks.

    When `file_list` is provided (or discoverable), queries Pinecone once PER
    FILE with a source_file filter, so every file contributes chunks even when
    one file dominates the relevance score. This prevents the "only 1 file in
    the answer" failure mode when the user uploads multiple files.

    Args:
        query: User's question.
        session_id: Chat session ID (Pinecone namespace).
        top_k: Total chunks to retrieve for single-file or unfiltered queries.
            For per-file retrieval, chunks-per-file is derived from this value
            and the file count (min 2, max 5 per file).
        file_list: Optional list of source filenames to search across. If None,
            we try to discover the files that exist in this session's namespace.

    Returns:
        List of dicts: [{"text": str, "source_file": str, "score": float}, ...]
    """
    from agentcore.services.ltm.embeddings import embed_single
    from agentcore.services.pinecone_service_client import async_search_via_service

    settings = _get_settings()
    index_name = settings.doc_qa_pinecone_index
    if top_k is None:
        top_k = settings.doc_qa_top_k

    logger.info(f"[DocQA] Generating query embedding for: '{query[:80]}...'")
    query_embedding = await embed_single(query)
    if not query_embedding:
        logger.warning("[DocQA] Failed to generate query embedding")
        return []
    logger.info(f"[DocQA] Query embedding generated (dim={len(query_embedding)})")

    import asyncio

    # Resolve which files to search across.
    files_to_search: list[str] = list(file_list) if file_list else []
    if not files_to_search:
        files_to_search = await _discover_session_files(
            index_name=index_name,
            namespace=session_id,
            query_embedding=query_embedding,
            query=query,
        )
        if files_to_search:
            logger.info(f"[DocQA] Discovered {len(files_to_search)} file(s) in session: {files_to_search}")

    # Pick per-file top-K. Single file → use the configured top_k as-is.
    # Multi-file → clamp 2-5 chunks per file so context stays manageable.
    if len(files_to_search) <= 1:
        per_file_k = top_k
    else:
        per_file_k = max(2, min(5, top_k))

    # Fallback path: no files known → run a single unfiltered query (legacy behavior).
    if not files_to_search:
        logger.info(f"[DocQA] No file list available, running unfiltered search (top_k={top_k})")
        for attempt in range(3):
            try:
                result = await async_search_via_service(
                    index_name=index_name,
                    namespace=session_id,
                    text_key="page_content",
                    query=query,
                    query_embedding=query_embedding,
                    number_of_results=top_k,
                )
                matches = result.get("results", []) or result.get("matches", [])
                chunks = _matches_to_chunks(matches)
                if chunks:
                    logger.info(f"[DocQA] Retrieved {len(chunks)} chunks (attempt {attempt + 1})")
                    return chunks
                if attempt < 2:
                    logger.info(f"[DocQA] 0 chunks, retrying in 5s (attempt {attempt + 1}/3)")
                    await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[DocQA] Pinecone search failed (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(5)
        logger.warning("[DocQA] Search returned 0 chunks after all retries")
        return []

    # Per-file retrieval path — one broad Pinecone query, then distribute the
    # returned chunks across files client-side. This is faster (single round
    # trip) and robust even when the Pinecone service layer does not forward
    # `metadata_filter` — any file that has ingested chunks will still surface.
    logger.info(
        f"[DocQA] Broad search + per-file distribute: {len(files_to_search)} file(s) "
        f"× {per_file_k} chunks each in namespace {session_id[:12]}..."
    )

    # Pull a generous buffer so every file gets a chance to contribute even
    # when one file's chunks dominate the top of the ranking.
    broad_top_k = max(per_file_k * len(files_to_search) * 3, 30)

    matches: list = []
    for attempt in range(3):
        try:
            result = await async_search_via_service(
                index_name=index_name,
                namespace=session_id,
                text_key="page_content",
                query=query,
                query_embedding=query_embedding,
                number_of_results=broad_top_k,
            )
            matches = result.get("results", []) or result.get("matches", [])
            if matches:
                break
            if attempt < 2:
                logger.info(f"[DocQA] Broad search returned 0, retrying in 5s ({attempt + 1}/3)")
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"[DocQA] Broad Pinecone search failed (attempt {attempt + 1}): {e}")
            if attempt < 2:
                await asyncio.sleep(5)

    # Log the distinct sources returned so mismatches jump out in the logs.
    # Some Pinecone service wrappers flatten metadata into the top level;
    # others keep a nested `metadata` dict. Probe both.
    def _find_source(m: dict) -> str | None:
        return (
            (m.get("metadata", {}) or {}).get("source_file")
            or m.get("source_file")
            or (m.get("metadata", {}) or {}).get("sourceFile")
            or m.get("sourceFile")
        )

    returned_sources: set[str] = set()
    for m in matches:
        s = _find_source(m)
        if s:
            returned_sources.add(s)
    logger.info(
        f"[DocQA] Broad search returned {len(matches)} match(es) covering "
        f"{len(returned_sources)} source file(s): {sorted(returned_sources)}"
    )
    logger.info(f"[DocQA] Files we expected to find: {files_to_search}")

    # Diagnostic: if we got matches but no source_file, dump the first match's
    # keys and a small sample so we can see where the metadata actually lives.
    if matches and not returned_sources:
        import json
        sample = matches[0]
        try:
            sample_keys = list(sample.keys()) if isinstance(sample, dict) else type(sample).__name__
            meta_keys = list((sample.get("metadata") or {}).keys()) if isinstance(sample, dict) else []
            logger.warning(
                f"[DocQA] DIAGNOSTIC: match top-level keys={sample_keys}, "
                f"metadata keys={meta_keys}"
            )
            # Truncated JSON dump of the first match for deeper inspection.
            dump = json.dumps(sample, default=str)[:800]
            logger.warning(f"[DocQA] DIAGNOSTIC: first match (truncated): {dump}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[DocQA] DIAGNOSTIC: could not dump sample match: {exc}")

    # Distribute: take top per_file_k chunks per expected file from the pool.
    by_file: dict[str, list[dict]] = {f: [] for f in files_to_search}
    for match in matches:
        source = _find_source(match)
        if not source or source not in by_file:
            continue
        if len(by_file[source]) >= per_file_k:
            continue
        text = _extract_match_text(match)
        if not text:
            continue
        by_file[source].append({
            "text": text,
            "source_file": source,
            "score": match.get("score", 0.0),
        })

    all_chunks: list[dict] = []
    missing: list[str] = []
    for file_name in files_to_search:
        file_chunks = by_file[file_name]
        logger.info(f"[DocQA]   {file_name}: {len(file_chunks)} chunk(s) from broad search")
        all_chunks.extend(file_chunks)
        if not file_chunks:
            missing.append(file_name)

    # Fallback for files that didn't surface in the broad search — try a
    # targeted filtered query in case the filter IS supported and the broad
    # search's top-K was too narrow.
    if missing:
        logger.info(
            f"[DocQA] {len(missing)} file(s) had 0 chunks from broad search; "
            f"attempting targeted filter as fallback: {missing}"
        )
        for file_name in missing:
            try:
                fb_result = await async_search_via_service(
                    index_name=index_name,
                    namespace=session_id,
                    text_key="page_content",
                    query=query,
                    query_embedding=query_embedding,
                    number_of_results=per_file_k,
                    metadata_filter={"source_file": {"$eq": file_name}},
                )
                fb_matches = fb_result.get("results", []) or fb_result.get("matches", [])
                fb_chunks = _matches_to_chunks(fb_matches, default_source=file_name)
                logger.info(f"[DocQA]   {file_name} (targeted): {len(fb_chunks)} chunk(s)")
                all_chunks.extend(fb_chunks)
            except Exception as e:
                logger.warning(f"[DocQA]   {file_name} (targeted) failed: {e}")

    logger.info(f"[DocQA] Retrieved {len(all_chunks)} total chunks across {len(files_to_search)} file(s)")
    return all_chunks


def _matches_to_chunks(matches: list, default_source: str | None = None) -> list[dict]:
    """Normalize Pinecone matches into [{text, source_file, score}, ...]."""
    chunks: list[dict] = []
    for match in matches:
        text = _extract_match_text(match)
        if not text:
            continue
        meta = match.get("metadata", {}) or {}
        source = meta.get("source_file") or match.get("source_file") or default_source or "unknown"
        chunks.append({
            "text": text,
            "source_file": source,
            "score": match.get("score", 0.0),
        })
    return chunks


# ---------------------------------------------------------------------------
# Build document Q&A prompt
# ---------------------------------------------------------------------------

def build_doc_qa_prompt(query: str, chunks: list) -> str:
    """Build an LLM prompt with document context, grouped by source file.

    Accepts either:
    - list[dict]  with {text, source_file, score} (new format)
    - list[str]   plain text chunks (legacy)

    When chunks carry source_file metadata, each file's chunks are grouped
    under a `[Source: filename]` header so the LLM can cite and reason across
    multiple files.
    """
    if not chunks:
        return query

    multi_file = False
    file_names: list[str] = []

    # Legacy format: plain strings — no source metadata available.
    if isinstance(chunks[0], str):
        context = "\n\n---\n\n".join(chunks)
    else:
        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        for c in chunks:
            src = c.get("source_file") or "unknown"
            if src not in grouped:
                grouped[src] = []
                order.append(src)
            grouped[src].append(c.get("text", ""))

        sections: list[str] = []
        for src in order:
            body = "\n\n".join(t for t in grouped[src] if t)
            if body:
                sections.append(f"[Source: {src}]\n{body}")
        context = "\n\n---\n\n".join(sections)
        file_names = order
        multi_file = len(order) > 1

    if multi_file:
        file_list_str = ", ".join(f'"{n}"' for n in file_names)
        instruction = (
            "You are answering a question based on multiple uploaded documents. "
            f"The documents are: {file_list_str}.\n\n"
            "STRICT RULES:\n"
            "1. Use ONLY the document context below — do not invent, guess, or bring in outside knowledge.\n"
            "2. Each chunk is prefixed with `[Source: filename]` showing which file it came from.\n"
            "3. When you describe content, ALWAYS name the specific file it came from "
            "(e.g. 'The file \"report.pdf\" explains...' or 'According to \"policy.txt\"...').\n"
            "4. If the question asks to summarise, describe, or list what the files contain "
            "(e.g. 'summarise these files', 'what do these documents cover'), produce a "
            "separate summary for EACH file, naming every file explicitly.\n"
            "5. Do NOT merge content from different files into one blurred paragraph — keep attribution clear.\n"
            "6. If the answer is not in the provided context, say so honestly."
        )
    else:
        only_file = file_names[0] if file_names else None
        file_hint = f' "{only_file}"' if only_file else ""
        instruction = (
            f"You are answering a question based on the uploaded document{file_hint}. "
            "Use ONLY the document context below to answer. "
            "If the answer is not in the context, say so."
        )

    return (
        f"{instruction}\n\n"
        f"## Document Context\n\n{context}\n\n"
        f"## Question\n\n{query}"
    )


# ---------------------------------------------------------------------------
# Session cleanup
# ---------------------------------------------------------------------------

async def cleanup_session_docs(session_id: str) -> None:
    """Delete all document vectors for a session from Pinecone.

    Called when a session is deleted or archived.
    """
    from agentcore.services.pinecone_service_client import delete_namespace_via_service

    settings = _get_settings()
    index_name = settings.doc_qa_pinecone_index

    try:
        delete_namespace_via_service(index_name=index_name, namespace=session_id)
        logger.info(f"[DocQA] Cleaned up Pinecone namespace for session {session_id}")
    except Exception as e:
        logger.warning(f"[DocQA] Failed to cleanup Pinecone namespace for session {session_id}: {e}")


# ---------------------------------------------------------------------------
# Check if session has documents
# ---------------------------------------------------------------------------

async def session_has_documents(session_id: str) -> bool:
    """Check if a session has any documents ingested in Pinecone.

    Checks the conversation history for messages with document file attachments.
    This is faster than querying Pinecone on every request.
    """
    from agentcore.services.mibuddy.document_extractor import SUPPORTED_DOC_EXTENSIONS
    from pathlib import Path

    try:
        from agentcore.services.deps import session_scope
        from agentcore.services.database.models.orch_conversation.crud import orch_get_messages

        async with session_scope() as db:
            messages = await orch_get_messages(db, session_id=session_id)

        logger.info(f"[DocQA] session_has_documents: checking {len(messages)} messages in session {session_id[:12]}...")
        for msg in messages:
            files = getattr(msg, "files", None) or []
            if files:
                logger.info(f"[DocQA] session_has_documents: found files={files}")
            for f in files:
                ext = Path(str(f)).suffix.lower()
                if ext in SUPPORTED_DOC_EXTENSIONS:
                    logger.info(f"[DocQA] session_has_documents: doc found! ext={ext} file={f}")
                    return True
        return False
    except Exception:
        return False
