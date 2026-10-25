import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key
from app.dependencies.rate_limit import enforce_embedding_rate_limits
from app.schemas import EmbeddingRequest, EmbeddingResponse
from app.services.embedding_service import embed
from app.services.rate_limiter import RateLimitContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["embeddings"])


@router.post("/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(
    request: EmbeddingRequest,
    _api_key: str = Depends(verify_api_key),
    rate_limit_ctx: RateLimitContext = Depends(enforce_embedding_rate_limits),
):
    """Generate embeddings for the provided input texts."""
    try:
        return await embed(request, rate_limit_ctx)
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Error generating embeddings")
        raise HTTPException(status_code=500, detail=f"Internal error: {e!s}") from e
