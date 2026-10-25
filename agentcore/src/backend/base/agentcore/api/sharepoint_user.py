"""SharePoint user-delegated API — OAuth popup flow for orchestrator file picker.

Provides endpoints for:
1. Getting the Microsoft OAuth authorization URL (frontend opens as popup)
2. Exchanging the auth code for an access token
3. Browsing OneDrive / SharePoint files with the user's token
4. Downloading a file and returning it as base64

All credentials come from environment variables populated by Key Vault at startup.
Uses the SharePointService template with static methods.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.sharepoint.user_delegated import SharePointService

router = APIRouter(prefix="/sharepoint-user", tags=["SharePoint User Delegated"])


# ── Request / Response models ───────────────────────────────────────

class AuthUrlRequest(BaseModel):
    redirect_uri: str
    state: str = ""


class TokenExchangeRequest(BaseModel):
    code: str
    redirect_uri: str


class BrowseRequest(BaseModel):
    access_token: str
    folder_id: str = ""


class SiteDrivesRequest(BaseModel):
    access_token: str
    site_id: str


class DriveItemsRequest(BaseModel):
    access_token: str
    drive_id: str
    folder_id: str = ""


class DownloadRequest(BaseModel):
    access_token: str
    item_id: str
    drive_id: str = ""
    filename: str = ""


class SearchRequest(BaseModel):
    access_token: str
    query: str


class ResolveUrlRequest(BaseModel):
    access_token: str
    sharing_url: str


# ── Helpers ──────────────────────────────────────────────────────────

def _format_items(items: list[dict]) -> list[dict]:
    """Normalize Graph API drive items into a consistent shape."""
    results = []
    for item in items:
        entry = {
            "id": item.get("id"),
            "name": item.get("name"),
            "size": item.get("size"),
            "lastModified": item.get("lastModifiedDateTime"),
            "webUrl": item.get("webUrl", ""),
            "type": "folder" if "folder" in item else "file",
        }
        if "file" in item:
            entry["mimeType"] = item["file"].get("mimeType", "")
        if "folder" in item:
            entry["childCount"] = item["folder"].get("childCount", 0)
        results.append(entry)
    return results


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/auth-url")
async def get_auth_url(
    req: AuthUrlRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Return the Microsoft OAuth authorization URL for the popup."""
    url = SharePointService.build_auth_url(
        redirect_uri=req.redirect_uri, state=req.state,
    )
    return {"auth_url": url}


@router.post("/token")
async def exchange_token(
    req: TokenExchangeRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Exchange an authorization code for an access token."""
    try:
        result = SharePointService.exchange_code_for_token(
            auth_code=req.code, redirect_uri=req.redirect_uri,
        )
        if result is None:
            raise HTTPException(status_code=400, detail="Token exchange failed")

        # Validate the token works
        user_info = SharePointService.validate_access_token(result["access_token"])

        return {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token"),
            "expires_in": result.get("expires_in", 3600),
            "user": user_info,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint token exchange error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to exchange token")


@router.post("/browse")
async def browse_files(
    req: BrowseRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Browse the user's OneDrive files (root or a folder)."""
    try:
        if req.folder_id:
            items = SharePointService.list_folder(req.access_token, req.folder_id)
        else:
            items = SharePointService.list_root_files(req.access_token)

        if items is None:
            raise HTTPException(status_code=400, detail="Failed to browse files")
        return {"items": _format_items(items)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint browse error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to browse files")


@router.post("/sites")
async def list_sites(
    req: BrowseRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """List SharePoint sites the user has access to."""
    try:
        sites = SharePointService.list_sharepoint_sites(req.access_token)
        if sites is None:
            raise HTTPException(status_code=400, detail="Failed to list sites")
        return {
            "sites": [
                {
                    "id": s.get("id"),
                    "name": s.get("displayName") or s.get("name"),
                    "webUrl": s.get("webUrl", ""),
                }
                for s in sites
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint list sites error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to list sites")


@router.post("/site-drives")
async def list_site_drives(
    req: SiteDrivesRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """List document libraries for a SharePoint site."""
    try:
        drives = SharePointService.list_site_drives(req.access_token, req.site_id)
        if drives is None:
            raise HTTPException(status_code=400, detail="Failed to list drives")
        return {
            "drives": [
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "webUrl": d.get("webUrl", ""),
                }
                for d in drives
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint list drives error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to list drives")


@router.post("/drive-items")
async def list_drive_items(
    req: DriveItemsRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """List items in a SharePoint drive."""
    try:
        items = SharePointService.list_drive_items(
            req.access_token, req.drive_id, req.folder_id,
        )
        if items is None:
            raise HTTPException(status_code=400, detail="Failed to list drive items")
        return {"items": _format_items(items)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint drive items error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to list drive items")


@router.post("/download")
async def download_file(
    req: DownloadRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Download a file and return it as base64 with metadata."""
    try:
        if req.drive_id:
            content = SharePointService.get_drive_file_content(
                req.access_token, req.drive_id, req.item_id,
            )
        else:
            content = SharePointService.get_file_content(
                req.access_token, req.item_id,
            )

        if content is None:
            raise HTTPException(status_code=400, detail="Failed to download file")

        return {
            "filename": req.filename or "file",
            "size": len(content),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint download error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to download file")


@router.post("/search")
async def search_files(
    req: SearchRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Search for files in the user's OneDrive."""
    try:
        items = SharePointService.search_files(req.access_token, req.query)
        if items is None:
            raise HTTPException(status_code=400, detail="Failed to search files")
        return {"items": _format_items(items)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint search error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to search files")


@router.post("/resolve-url")
async def resolve_url(
    req: ResolveUrlRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Resolve a SharePoint sharing URL to a DriveItem."""
    try:
        result = SharePointService.resolve_sharepoint_url(
            req.access_token, req.sharing_url,
        )
        if result is None:
            raise HTTPException(status_code=400, detail="Failed to resolve share link")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"SharePoint resolve URL error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to resolve share link")
