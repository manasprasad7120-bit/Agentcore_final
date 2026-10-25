import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env into os.environ so unprefixed shared vars (REDIS_HOST,
# REDIS_ENTRA_SCOPE, etc.) are visible to modules that read os.getenv
# directly. pydantic-settings only feeds the prefixed values into Settings.
load_dotenv()

from app.config import get_settings
from app.routers.chat import router as chat_router
from app.routers.embeddings import router as embeddings_router
from app.routers.models import router as models_router
from app.routers.registry import router as registry_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Renamed from `app` to `application` because ``import app.providers``
    # below rebinds the local name `app` to the package, shadowing the
    # parameter and breaking later ``app.state`` writes.
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    logger.info("Model Service starting on %s:%s", settings.host, settings.port)
    if not settings.key_vault_url:
        logger.warning(
            "MODEL_SERVICE_KEY_VAULT_URL is not set: running without Azure Key Vault. "
            "Provider API keys will be kept in the local encrypted secret store "
            "(see app/utils/local_secrets.py). Set MODEL_SERVICE_KEY_VAULT_URL for production."
        )

    # Import providers to trigger registration
    import app.providers  # noqa: F401

    # Initialise database if configured
    if settings.database_url:
        from app.database import init_db
        from app.services.packages import sync_packages_to_db

        await init_db(settings.database_url)
        logger.info("Database connected")
        try:
            await sync_packages_to_db()
            logger.info("Model-service package sync completed")
        except Exception:  # pragma: no cover - startup should not fail on package sync issues
            logger.exception("Model-service package sync failed during startup")

    # Per-model rate limiter. Connects to the same managed Redis the backend
    # uses (REDIS_HOST / REDIS_ENTRA_* env vars). Fail-open by default so a
    # Redis outage degrades gracefully; flip
    # MODEL_SERVICE_RATE_LIMIT_FAIL_MODE=closed for compliance.
    application.state.rate_limiter = None
    if settings.rate_limit_enabled:
        from app.services.rate_limiter import RateLimiter
        from app.services.redis_client import build_redis_client, is_redis_configured

        if not is_redis_configured():
            logger.warning(
                "Rate limiting enabled but REDIS_HOST is unset; skipping limiter init. "
                "Set REDIS_HOST/REDIS_PORT/REDIS_ENTRA_SCOPE to enforce per-model RPM/TPM."
            )
        else:
            try:
                redis_client = build_redis_client()
                application.state.rate_limiter = await RateLimiter.create(
                    redis_client,
                    fail_mode=settings.rate_limit_fail_mode,
                )
                logger.info(
                    "Rate limiter ready (host=%s, fail_mode=%s)",
                    os.getenv("REDIS_HOST", "?"),
                    settings.rate_limit_fail_mode,
                )
            except ConnectionError:
                logger.exception("Rate limiter init failed (fail_mode=closed)")
                raise
            except Exception:  # noqa: BLE001
                if settings.rate_limit_fail_mode == "closed":
                    raise
                logger.exception(
                    "Rate limiter init failed; continuing without rate limiting "
                    "(MODEL_SERVICE_RATE_LIMIT_FAIL_MODE=open)"
                )
    else:
        logger.info("Rate limiting disabled (MODEL_SERVICE_RATE_LIMIT_ENABLED=false)")

    yield
    logger.info("Model Service shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="Model Service",
        description="OpenAI-compatible Model microservice (LLM & Embeddings) for AgentCore",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    origins = [origin.strip() for origin in settings.cors_origins.split(",")]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    application.include_router(chat_router)
    application.include_router(embeddings_router)
    application.include_router(models_router)
    application.include_router(registry_router)

    @application.get("/health")
    async def health():
        redis_status = "disabled"
        limiter = getattr(application.state, "rate_limiter", None)
        if limiter is not None:
            redis_status = "ok" if await limiter.ping() else "degraded"
        return {
            "status": "healthy",
            "service": "model-service",
            "version": "1.0.0",
            "redis": redis_status,
        }

    return application


app = create_app()


def run():
    """Entry point for the model-service script."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
