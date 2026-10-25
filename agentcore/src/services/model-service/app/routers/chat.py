import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import verify_api_key
from app.dependencies.rate_limit import enforce_chat_rate_limits
from app.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.services.model_service import chat_completion, chat_completion_stream
from app.services.rate_limiter import RateLimitContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])


def _rate_limit_headers(ctx: RateLimitContext) -> dict[str, str]:
    """Render the X-RateLimit-* headers from a context for StreamingResponse.

    The FastAPI-injected ``Response`` object only carries headers for unary
    responses; streaming responses build their own header dict, so we
    re-render here from the context the dependency returned.
    """
    headers: dict[str, str] = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if ctx.rpm_result is not None:
        headers["X-RateLimit-RPM-Limit"] = str(ctx.rpm_result.limit)
        headers["X-RateLimit-RPM-Remaining"] = str(ctx.rpm_result.remaining)
        headers["X-RateLimit-RPM-Reset"] = str(ctx.rpm_result.reset_at)
    if ctx.tpm_result is not None:
        headers["X-RateLimit-TPM-Limit"] = str(ctx.tpm_result.limit)
        headers["X-RateLimit-TPM-Remaining"] = str(ctx.tpm_result.remaining)
        headers["X-RateLimit-TPM-Reset"] = str(ctx.tpm_result.reset_at)
    return headers


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    _api_key: str = Depends(verify_api_key),
    rate_limit_ctx: RateLimitContext = Depends(enforce_chat_rate_limits),
):
    """Create a chat completion. Supports streaming and non-streaming modes."""
    try:
        if request.stream:
            return StreamingResponse(
                chat_completion_stream(request, rate_limit_ctx),
                media_type="text/event-stream",
                headers=_rate_limit_headers(rate_limit_ctx),
            )
        return await chat_completion(request, rate_limit_ctx)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Error processing chat completion")
        raise HTTPException(status_code=500, detail=f"Internal error: {e!s}") from e
