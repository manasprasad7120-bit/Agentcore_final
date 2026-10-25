"""Pinecone vector store endpoints."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key
from app.schemas import (
    CopyNamespaceRequest,
    CopyNamespaceResponse,
    DeleteIndexRequest,
    DeleteIndexResponse,
    DeleteNamespaceRequest,
    DeleteNamespaceResponse,
    DeleteVectorsRequest,
    DeleteVectorsResponse,
    EnsureIndexRequest,
    EnsureIndexResponse,
    IngestRequest,
    IngestResponse,
    ListIndexesResponse,
    NamespaceStatsRequest,
    NamespaceStatsResponse,
    SearchRequest,
    SearchResponse,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.services.pinecone_service import (
    copy_namespace,
    delete_index,
    delete_namespace,
    delete_vectors,
    ensure_index,
    get_namespace_stats,
    ingest_documents,
    list_indexes,
    search_documents,
    test_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/pinecone", tags=["Pinecone"], dependencies=[Depends(verify_api_key)])


_executor = ThreadPoolExecutor(max_workers=10)


async def _run_sync(func, *args):
    """Run a blocking function in a bounded executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, partial(func, *args))


@router.post("/ensure-index", response_model=EnsureIndexResponse)
async def ensure_index_endpoint(req: EnsureIndexRequest):
    try:
        return await _run_sync(ensure_index, req)
    except ValueError as e:
        logger.error("ensure_index failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ensure_index failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during index creation")


@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(req: IngestRequest):
    try:
        return await _run_sync(ingest_documents, req)
    except ValueError as e:
        logger.error("ingest failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ingest failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during document ingestion")


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest):
    try:
        return await _run_sync(search_documents, req)
    except ValueError as e:
        logger.error("search failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during search")


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection_endpoint(req: TestConnectionRequest):
    return await _run_sync(test_connection, req)


@router.post("/copy-namespace", response_model=CopyNamespaceResponse)
async def copy_namespace_endpoint(req: CopyNamespaceRequest):
    """Copy all vectors from one namespace to another (used for UAT → PROD migration)."""
    try:
        return await _run_sync(copy_namespace, req)
    except ValueError as e:
        logger.error("copy_namespace failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("copy_namespace failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during namespace copy")


@router.post("/namespace-stats", response_model=NamespaceStatsResponse)
async def namespace_stats_endpoint(req: NamespaceStatsRequest):
    """Return vector count and dimension for a namespace (observability)."""
    try:
        return await _run_sync(get_namespace_stats, req)
    except ValueError as e:
        logger.error("namespace_stats failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("namespace_stats failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching namespace stats")


@router.get("/indexes", response_model=ListIndexesResponse)
async def list_indexes_endpoint():
    """List all Pinecone indexes with namespaces and vector counts."""
    try:
        return await _run_sync(list_indexes)
    except Exception as e:
        logger.error("list_indexes failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error listing indexes")


@router.post("/delete-index", response_model=DeleteIndexResponse)
async def delete_index_endpoint(req: DeleteIndexRequest):
    """Delete an entire Pinecone index."""
    try:
        return await _run_sync(delete_index, req)
    except ValueError as e:
        logger.error("delete_index failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("delete_index failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error deleting index")


@router.post("/delete-namespace", response_model=DeleteNamespaceResponse)
async def delete_namespace_endpoint(req: DeleteNamespaceRequest):
    """Delete all vectors in a namespace."""
    try:
        return await _run_sync(delete_namespace, req)
    except ValueError as e:
        logger.error("delete_namespace failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("delete_namespace failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error deleting namespace")


@router.post("/delete-vectors", response_model=DeleteVectorsResponse)
async def delete_vectors_endpoint(req: DeleteVectorsRequest):
    """Delete specific vectors by their IDs."""
    try:
        return await _run_sync(delete_vectors, req)
    except ValueError as e:
        logger.error("delete_vectors failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("delete_vectors failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error deleting vectors")
