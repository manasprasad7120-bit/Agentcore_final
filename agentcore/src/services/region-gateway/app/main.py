from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, load_regions, get_regions, get_region_by_code
from app.proxy import region_proxy

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info("Region Gateway starting on %s:%s", settings.host, settings.port)

    regions = load_regions(settings)
    logger.info("Loaded %d region(s): %s", len(regions), [r.code for r in regions])

    yield

    await region_proxy.close()
    logger.info("Region Gateway shut down")


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="Region Gateway",
        description="Cross-region dashboard proxy for AgentCore",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── List all regions ──────────────────────────────────────────────────

    @application.get("/api/regions")
    async def list_regions():
        """Return all registered regions (called by hub backend on behalf of root admin)."""
        regions = get_regions()
        return [
            {
                "code": r.code,
                "name": r.name,
                "is_hub": r.is_hub,
            }
            for r in regions
        ]

    # ── Proxy dashboard request to a spoke ────────────────────────────────

    @application.get("/api/regions/{region_code}/dashboard/{section:path}")
    async def proxy_dashboard(
        region_code: str,
        section: str,
        caller: str | None = Query(default=None, description="Root admin user ID"),
        org_id: str | None = Query(default=None),
        range: str | None = Query(default=None),
        tz_offset_minutes: int | None = Query(default=None),
    ):
        """Proxy a dashboard section request to the spoke region's backend.

        The hub backend calls this endpoint; the frontend never calls it directly.
        """
        region = get_region_by_code(region_code)
        if region is None:
            raise HTTPException(status_code=404, detail=f"Region '{region_code}' not found")

        # Build query params to forward (only non-None values)
        query_params: dict = {}
        if org_id:
            query_params["org_id"] = org_id
        if range:
            query_params["range"] = range
        if tz_offset_minutes is not None:
            query_params["tz_offset_minutes"] = str(tz_offset_minutes)

        try:
            data = await region_proxy.proxy_dashboard(
                region=region,
                path=f"/api/dashboard/sections/{section}",
                query_params=query_params,
                caller_user_id=caller,
            )
            return data
        except RuntimeError as e:
            # Circuit breaker open
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error("Proxy error for region '%s': %s", region_code, e, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach region '{region_code}': {type(e).__name__}",
            )

    @application.get("/api/regions/{region_code}/releases")
    @application.get("/api/regions/{region_code}/releases/{release_path:path}")
    async def proxy_releases(
        region_code: str,
        release_path: str = "",
        caller: str | None = Query(default=None, description="Root admin user ID"),
        service: str | None = Query(default=None),
    ):
        """Proxy release management requests to a spoke backend."""
        region = get_region_by_code(region_code)
        if region is None:
            raise HTTPException(status_code=404, detail=f"Region '{region_code}' not found")

        query_params: dict = {}
        if service:
            query_params["service"] = service

        target_path = "/api/releases"
        if release_path:
            target_path = f"{target_path}/{release_path}"

        try:
            if release_path.endswith("/document/download"):
                content, headers, media_type = await region_proxy.proxy_bytes(
                    region=region,
                    path=target_path,
                    query_params=query_params,
                    caller_user_id=caller,
                )
                return Response(
                    content=content,
                    media_type=media_type or "application/octet-stream",
                    headers=headers,
                )

            return await region_proxy.proxy_json(
                region=region,
                path=target_path,
                query_params=query_params,
                caller_user_id=caller,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error("Release proxy error for region '%s': %s", region_code, e, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach region '{region_code}': {type(e).__name__}",
            )

    @application.post("/api/regions/{region_code}/releases/bump-with-document")
    async def proxy_release_create(
        region_code: str,
        caller: str | None = Query(default=None, description="Root admin user ID"),
        bump_type: str = Form(...),
        release_notes: str | None = Form(default=None),
        document_file: UploadFile | None = File(default=None),
    ):
        """Proxy release creation to a spoke backend."""
        region = get_region_by_code(region_code)
        if region is None:
            raise HTTPException(status_code=404, detail=f"Region '{region_code}' not found")
        if document_file is None:
            raise HTTPException(status_code=400, detail="Release document is required.")

        content = await document_file.read()
        files = {
            "document_file": (
                document_file.filename or "release-notes.docx",
                content,
                document_file.content_type
                or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        form_data = {"bump_type": bump_type}
        if release_notes and release_notes.strip():
            form_data["release_notes"] = release_notes.strip()

        try:
            return await region_proxy.proxy_multipart(
                region=region,
                path="/api/releases/bump-with-document",
                data=form_data,
                files=files,
                caller_user_id=caller,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error("Release create proxy error for region '%s': %s", region_code, e, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach region '{region_code}': {type(e).__name__}",
            )

    @application.get("/api/regions/{region_code}/packages")
    @application.get("/api/regions/{region_code}/packages/{package_path:path}")
    async def proxy_packages_get(
        region_code: str,
        package_path: str = "",
        caller: str | None = Query(default=None, description="Root admin user ID"),
        include_history: bool | None = Query(default=None),
        include_full_graph: bool | None = Query(default=None),
        service: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ):
        """Proxy package reads to a spoke backend."""
        region = get_region_by_code(region_code)
        if region is None:
            raise HTTPException(status_code=404, detail=f"Region '{region_code}' not found")

        query_params: dict[str, str] = {}
        if include_history is not None:
            query_params["include_history"] = str(include_history).lower()
        if include_full_graph is not None:
            query_params["include_full_graph"] = str(include_full_graph).lower()
        if service:
            query_params["service"] = service
        if status:
            query_params["status"] = status

        target_path = "/api/packages"
        if package_path:
            target_path = f"{target_path}/{package_path}"

        try:
            return await region_proxy.proxy_json(
                region=region,
                path=target_path,
                query_params=query_params,
                caller_user_id=caller,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error("Packages proxy error for region '%s': %s", region_code, e, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach region '{region_code}': {type(e).__name__}",
            )

    @application.post("/api/regions/{region_code}/packages/{package_path:path}")
    async def proxy_packages_post(
        region_code: str,
        package_path: str,
        caller: str | None = Query(default=None, description="Root admin user ID"),
        payload: dict | None = Body(default=None),
    ):
        """Proxy package mutations to a spoke backend."""
        region = get_region_by_code(region_code)
        if region is None:
            raise HTTPException(status_code=404, detail=f"Region '{region_code}' not found")

        try:
            return await region_proxy.proxy_json_request(
                region=region,
                method="POST",
                path=f"/api/packages/{package_path}",
                caller_user_id=caller,
                json_body=payload or {},
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error("Packages proxy mutation error for region '%s': %s", region_code, e, exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach region '{region_code}': {type(e).__name__}",
            )

    # ── Health check for a specific spoke ─────────────────────────────────

    @application.get("/api/regions/{region_code}/health")
    async def region_health(region_code: str):
        """Check health of a specific spoke region."""
        region = get_region_by_code(region_code)
        if region is None:
            raise HTTPException(status_code=404, detail=f"Region '{region_code}' not found")

        result = await region_proxy.check_health(region)
        return {"region": region_code, **result}

    # ── Gateway's own health ──────────────────────────────────────────────

    @application.get("/health")
    async def health():
        return {"status": "ok", "service": "region-gateway"}

    return application


app = create_app()


def run():
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
    
if __name__ == "__main__":
    run()
