"""FastAPI dependency that runs the per-model RPM + TPM pre-flight check.

The dependency lives outside the route handler so it can short-circuit with a
429 BEFORE the provider is dialed. It returns a ``RateLimitContext`` carrying
the snapshots and a bound ``debit_tpm`` callable -- the route handler / service
layer invokes that callable post-call to charge the actual token count against
the TPM window.

Models without a ``registry_model_id`` (i.e. ad-hoc provider+model calls that
don't reference a row in ``model_registry``) are passed through unconstrained,
because per-model limits live on the registry row.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response

from app.config import get_settings
from app.database import get_session
from app.schemas import ChatCompletionRequest, EmbeddingRequest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.rate_limiter import RateLimitContext

logger = logging.getLogger(__name__)


# Header names follow the de-facto convention used by GitHub / OpenAI but split
# RPM and TPM since we expose both. Reset is a unix timestamp (seconds).
_HEADERS = {
    "rpm": ("X-RateLimit-RPM-Limit", "X-RateLimit-RPM-Remaining", "X-RateLimit-RPM-Reset"),
    "tpm": ("X-RateLimit-TPM-Limit", "X-RateLimit-TPM-Remaining", "X-RateLimit-TPM-Reset"),
}


def _extract_registry_model_id(provider_config: dict) -> UUID | None:
    raw = provider_config.get("registry_model_id") if provider_config else None
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _apply_headers(response: Response | None, ctx: RateLimitContext) -> None:
    if response is None:
        return
    for kind, snap in (("rpm", ctx.rpm_result), ("tpm", ctx.tpm_result)):
        if snap is None:
            continue
        limit_h, remaining_h, reset_h = _HEADERS[kind]
        response.headers[limit_h] = str(snap.limit)
        response.headers[remaining_h] = str(snap.remaining)
        response.headers[reset_h] = str(snap.reset_at)


async def _enforce(
    request_obj: ChatCompletionRequest | EmbeddingRequest,
    fastapi_request: Request,
    response: Response,
    session: AsyncSession,
) -> RateLimitContext:
    from app.services.rate_limiter import NULL_CONTEXT, RateLimitExceeded

    settings = get_settings()
    limiter = getattr(fastapi_request.app.state, "rate_limiter", None)

    if limiter is None or not settings.rate_limit_enabled:
        return NULL_CONTEXT

    model_id = _extract_registry_model_id(request_obj.provider_config or {})
    if model_id is None:
        # Ad-hoc calls without a registry row aren't subject to per-model limits.
        return NULL_CONTEXT

    # Service-layer import to avoid a circular at module load: registry_service
    # imports from app.config, which is loaded before this dependency.
    from app.services.registry_service import get_rate_limits

    row_rpm, row_tpm = await get_rate_limits(session, model_id)
    rpm = row_rpm if row_rpm is not None else settings.rate_limit_default_rpm
    tpm = row_tpm if row_tpm is not None else settings.rate_limit_default_tpm

    if not rpm and not tpm:
        return NULL_CONTEXT

    try:
        ctx = await limiter.enforce(model_id, rpm=rpm, tpm=tpm)
    except RateLimitExceeded as exc:
        client_host = fastapi_request.client.host if fastapi_request.client else "?"
        logger.warning(
            "rate_limit_exceeded type=%s model_id=%s limit=%d retry_after=%d caller=%s",
            exc.limit_type.value, model_id, exc.limit, exc.retry_after_seconds, client_host,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "limit_type": exc.limit_type.value,
                "limit": exc.limit,
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from None

    _apply_headers(response, ctx)
    return ctx


async def enforce_chat_rate_limits(
    request: ChatCompletionRequest,
    fastapi_request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> RateLimitContext:
    """Dependency for /v1/chat/completions. Returns the context for post-debit."""
    return await _enforce(request, fastapi_request, response, session)


async def enforce_embedding_rate_limits(
    request: EmbeddingRequest,
    fastapi_request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> RateLimitContext:
    """Dependency for /v1/embeddings. Returns the context for post-debit."""
    return await _enforce(request, fastapi_request, response, session)
