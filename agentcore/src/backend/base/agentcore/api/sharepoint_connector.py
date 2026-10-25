"""SharePoint connector API — document library operations via Microsoft Graph.

Isolated router for SharePoint-specific operations. Does NOT modify
any connector-catalogue CRUD — that remains in connector_catalogue.py.

Uses client-credentials (app-only) authentication — no OAuth user flow needed.
"""
from __future__ import annotations

import asyncio
import base64
import threading
from uuid import UUID

import httpx
from cachetools import TTLCache
from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from agentcore.api.connector_catalogue import (
    STORAGE_PROVIDERS,
    _can_access_connector,
    _decrypt_provider_config,
    _get_scope_memberships,
    _require_connector_permission,
)
from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue
from agentcore.services.permissions import (
    ConnectorPermissionError,
    graph_permission_error_message,
    has_any_scope,
    is_graph_permission_error,
)
from agentcore.services.sharepoint.graph_sharepoint import (
    SHAREPOINT_WRITE_SCOPES,
    SharePointGraphClient,
)

router = APIRouter(prefix="/sharepoint", tags=["SharePoint Connector"])


# ── Path traversal guard (Step 1) ─────────────────────────────────

def _validate_path(path: str, label: str = "path") -> None:
    """Reject path values that could escape the intended directory."""
    if not path:
        return
    if "\x00" in path:
        raise ValueError(f"Invalid {label}: null bytes are not allowed")
    if "\\" in path:
        raise ValueError(f"Invalid {label}: backslashes are not allowed (use forward slashes)")
    for segment in path.replace("//", "/").split("/"):
        if segment == "..":
            raise ValueError(f"Invalid {label}: path traversal ('..') is not allowed")


# ── Pydantic request models ──────────────────────────────────────

class ListFilesRequest(BaseModel):
    library: str = "Shared Documents"
    folder_path: str = ""
    top: int = 50


class ReadFileRequest(BaseModel):
    library: str = "Shared Documents"
    item_id: str


class UploadFileRequest(BaseModel):
    library: str = "Shared Documents"
    folder_path: str = ""
    filename: str
    content_base64: str  # base64-encoded file content


class SearchFilesRequest(BaseModel):
    library: str = "Shared Documents"
    query: str


class CreateFolderRequest(BaseModel):
    library: str = "Shared Documents"
    parent_path: str = ""
    folder_name: str


# ── Client cache (Step 4) ────────────────────────────────────────

_client_cache: TTLCache = TTLCache(maxsize=32, ttl=300)
_client_cache_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────

async def _load_connector(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> ConnectorCatalogue:
    """Load and validate a connector belongs to the user and is a SharePoint connector."""
    await _require_connector_permission(current_user, "view_connector_page")
    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    if row.provider != "sharepoint":
        raise HTTPException(status_code=400, detail="Not a SharePoint connector")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Connector is outside your visibility scope")
    return row


def _get_decrypted_config(row: ConnectorCatalogue) -> dict:
    """Get decrypted provider_config for a connector."""
    return _decrypt_provider_config(row.provider, row.provider_config or {})


def _build_graph_client(config: dict) -> SharePointGraphClient:
    """Construct a SharePointGraphClient from decrypted connector config.

    Returns a cached client if one exists for this (tenant, client, site) tuple (Step 4).
    """
    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")
    site_url = config.get("site_url", "")

    if not all([tenant_id, client_id, client_secret, site_url]):
        raise HTTPException(
            status_code=400,
            detail="Missing required SharePoint config (tenant_id, client_id, client_secret, site_url)",
        )

    cache_key = (tenant_id, client_id, site_url)
    with _client_cache_lock:
        cached = _client_cache.get(cache_key)
        if cached is not None:
            return cached

    client = SharePointGraphClient(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        site_url=site_url,
    )

    with _client_cache_lock:
        _client_cache[cache_key] = client

    return client


async def _gate_with_refresh_retry(
    client: SharePointGraphClient,
    coro_factory,
):
    """Run a SharePoint write coroutine with force-refresh on local-gate denial.

    Pattern mirrors the Outlook ``_gate_with_refresh_retry`` helper. When the
    locally-cached ``granted_roles`` is stale (admin granted Sites.ReadWrite.All
    *after* the token was issued, but the in-process token cache hasn't
    expired yet), the first call raises ``ConnectorPermissionError`` even
    though Graph would now accept the operation. Force-refresh the token,
    re-decode the roles claim, and re-try once.

    If the second attempt still raises, that means the role really isn't
    granted — surface the original exception so the caller can render the
    canonical 403 message.
    """
    try:
        return await coro_factory()
    except ConnectorPermissionError:
        # Local gate denied — re-acquire token in case admin granted the role
        # since the last token issue. invalidate_token() zeros the cached
        # access token; the next call to _acquire_token() pulls a fresh one
        # and re-runs parse_jwt_roles on it.
        client.invalidate_token()
        # The retry will go through the same gate again with fresh roles.
        return await coro_factory()


async def _retry_on_transient(client: SharePointGraphClient, coro_factory, max_retries: int = 3):
    """Execute an async operation with retry logic for 401, 429, and 5xx errors (Step 2).

    The Graph client's ``_request()`` handles most retries internally, but this
    covers higher-level coroutines (e.g. ``resolve_drive_id`` which chains calls).
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            # 401 — re-acquire token, retry once
            if status == 401 and attempt == 0:
                logger.warning("SharePoint Graph API 401, re-acquiring token and retrying")
                client.invalidate_token()
                continue
            # 429 — respect Retry-After
            if status == 429:
                retry_after = float(exc.response.headers.get("Retry-After", "2"))
                retry_after = min(retry_after, 30)
                logger.warning(f"SharePoint Graph API 429, retrying after {retry_after}s")
                await asyncio.sleep(retry_after)
                last_exc = exc
                continue
            # 5xx — exponential backoff
            if status in (500, 502, 503, 504):
                backoff = min(2 ** attempt, 8)
                logger.warning(f"SharePoint Graph API {status}, retrying after {backoff}s")
                await asyncio.sleep(backoff)
                last_exc = exc
                continue
            raise
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            backoff = min(2 ** attempt, 8)
            logger.warning(f"SharePoint connection error: {exc}, retrying after {backoff}s")
            await asyncio.sleep(backoff)
            last_exc = exc
            continue

    if last_exc:
        raise last_exc


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/{connector_id}/capabilities")
async def get_capabilities(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Probe the SharePoint connector's actual Graph capabilities.

    Acquires an app-only token, decodes its ``roles`` claim, and runs a
    minimum read probe (``list_drives``) to *verify* read access — rather
    than assuming it. The frontend uses the returned ``can_read`` /
    ``can_write`` to hide controls when the connector is reduced.

    All three checks are explicit:
        * ``token_acquired``  — Did the client_credentials exchange succeed?
        * ``can_read``        — Did a real Graph call succeed?
        * ``can_write``       — Is ``Sites.ReadWrite.All`` in the JWT roles?
    """
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    token_acquired = False
    roles: list[str] = []
    can_read = False
    read_probe_error: str | None = None

    # Step 1: acquire token (also decodes roles)
    try:
        await client._acquire_token()
        token_acquired = True
        roles = client.granted_roles
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Token acquisition failed ({exc.response.status_code}): {exc.response.text[:300]}",
        )
    except Exception as exc:
        logger.warning(f"SharePoint capabilities — token acquisition failed for {connector_id}: {exc}")
        # Without a token we cannot determine anything. Return permissive
        # defaults (frontend shows all controls; backend gates fire on use).
        return {
            "connector_id": str(connector_id),
            "granted_roles": [],
            "token_acquired": False,
            "can_read": True,   # permissive fallback
            "can_write": True,  # permissive fallback
            "read_probe_error": str(exc),
        }

    # Step 2: real read probe — list_drives is the cheapest read call
    try:
        await client.list_drives()
        can_read = True
    except httpx.HTTPStatusError as exc:
        if is_graph_permission_error(exc.response.status_code, exc.response.text):
            read_probe_error = (
                f"Graph rejected list_drives with {exc.response.status_code} — "
                f"the app registration likely lacks Sites.Read.All (or "
                f"Sites.Selected was not granted on this site)."
            )
        else:
            read_probe_error = f"Graph error {exc.response.status_code}: {exc.response.text[:200]}"
        can_read = False
    except Exception as exc:
        read_probe_error = f"Probe failed: {exc!s}"
        can_read = False

    # Step 3: write capability — derived from JWT roles claim.
    # A write is authorised by ANY of: Sites.ReadWrite.All, Files.ReadWrite.All,
    # or Sites.Selected (per-site grants outside the JWT). ``has_any_scope``
    # encodes the same tristate as has_scope: None=legacy permissive,
    # []=strict deny, [...]=intersection check.
    can_write = has_any_scope(roles or None, SHAREPOINT_WRITE_SCOPES) if roles else True

    return {
        "connector_id": str(connector_id),
        "granted_roles": roles,
        "token_acquired": token_acquired,
        "can_read": can_read,
        "can_write": can_write,
        "read_probe_error": read_probe_error,
    }


@router.get("/{connector_id}/libraries")
async def list_libraries(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    """List all document libraries (drives) for the SharePoint site."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    try:
        drives = await _retry_on_transient(client, client.list_drives)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list libraries: {exc!s}")

    return [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "description": d.get("description", ""),
            "webUrl": d.get("webUrl", ""),
            "driveType": d.get("driveType", ""),
            "itemCount": d.get("quota", {}).get("used", 0),
        }
        for d in drives
    ]


@router.post("/{connector_id}/list")
async def list_files(
    connector_id: UUID,
    req: ListFilesRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """List files and folders in a document library path."""
    _validate_path(req.folder_path, "folder_path")

    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    try:
        drive_id = await _retry_on_transient(
            client, lambda: client.resolve_drive_id(req.library)
        )
        items = await _retry_on_transient(
            client, lambda: client.list_items(drive_id, req.folder_path, req.top)
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {exc!s}")

    results = []
    for item in items:
        entry = {
            "id": item.get("id"),
            "name": item.get("name"),
            "size": item.get("size"),
            "lastModified": item.get("lastModifiedDateTime"),
            "created": item.get("createdDateTime"),
            "webUrl": item.get("webUrl", ""),
            "type": "folder" if "folder" in item else "file",
        }
        if "file" in item:
            entry["mimeType"] = item["file"].get("mimeType", "")
        if "folder" in item:
            entry["childCount"] = item["folder"].get("childCount", 0)
        results.append(entry)

    return {
        "library": req.library,
        "folder_path": req.folder_path,
        "count": len(results),
        "items": results,
    }


@router.post("/{connector_id}/read")
async def read_file(
    connector_id: UUID,
    req: ReadFileRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Download and return a file's content (base64) and metadata."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    try:
        drive_id = await _retry_on_transient(
            client, lambda: client.resolve_drive_id(req.library)
        )
        metadata = await _retry_on_transient(
            client, lambda: client.get_file_metadata(drive_id, req.item_id)
        )
        content_bytes = await _retry_on_transient(
            client, lambda: client.read_file(drive_id, req.item_id)
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc!s}")

    return {
        "id": metadata.get("id"),
        "name": metadata.get("name"),
        "size": metadata.get("size"),
        "mimeType": metadata.get("file", {}).get("mimeType", ""),
        "lastModified": metadata.get("lastModifiedDateTime"),
        "webUrl": metadata.get("webUrl", ""),
        "content_base64": base64.b64encode(content_bytes).decode("ascii"),
    }


@router.post("/{connector_id}/upload")
async def upload_file(
    connector_id: UUID,
    req: UploadFileRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Upload a file to a SharePoint document library."""
    _validate_path(req.folder_path, "folder_path")
    _validate_path(req.filename, "filename")

    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    try:
        content_bytes = base64.b64decode(req.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 content")

    try:
        drive_id = await _retry_on_transient(
            client, lambda: client.resolve_drive_id(req.library)
        )
        # Use _gate_with_refresh_retry so an admin who granted
        # Sites.ReadWrite.All (or Files.ReadWrite.All) *after* the token
        # was issued doesn't have to wait for the ~1h token TTL to expire
        # before the user can upload.
        result = await _gate_with_refresh_retry(
            client,
            lambda: client.upload_file(drive_id, req.folder_path, req.filename, content_bytes),
        )
    except ConnectorPermissionError as exc:
        # Local gate denied even after force-refresh — the role really
        # isn't granted. Surface a clean 403 with a message the client
        # can show, instead of letting Graph return an opaque
        # "Insufficient privileges" upstream error.
        raise HTTPException(status_code=403, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        # Stale-revocation safety net: detect Graph permission errors that
        # slipped past our local gate (legacy permissive fallback, admin
        # revoked write since token issued, or Sites.Selected without
        # per-site grant on this site).
        if is_graph_permission_error(exc.response.status_code, exc.response.text):
            raise HTTPException(
                status_code=403,
                detail=graph_permission_error_message(
                    "Sites.ReadWrite.All",
                    operation="upload",
                    graph_status=exc.response.status_code,
                    graph_body=exc.response.text,
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {exc!s}")

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "size": result.get("size"),
        "webUrl": result.get("webUrl", ""),
        "message": f"File '{req.filename}' uploaded successfully",
    }


@router.post("/{connector_id}/search")
async def search_files(
    connector_id: UUID,
    req: SearchFilesRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Search for files by keyword within a document library."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    try:
        drive_id = await _retry_on_transient(
            client, lambda: client.resolve_drive_id(req.library)
        )
        items = await _retry_on_transient(
            client, lambda: client.search_files(drive_id, req.query)
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to search files: {exc!s}")

    results = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "size": item.get("size"),
            "lastModified": item.get("lastModifiedDateTime"),
            "webUrl": item.get("webUrl", ""),
            "type": "folder" if "folder" in item else "file",
        }
        for item in items
    ]

    return {
        "library": req.library,
        "query": req.query,
        "count": len(results),
        "items": results,
    }


@router.post("/{connector_id}/create-folder")
async def create_folder(
    connector_id: UUID,
    req: CreateFolderRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Create a new folder in a SharePoint document library."""
    _validate_path(req.parent_path, "parent_path")
    _validate_path(req.folder_name, "folder_name")

    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)
    client = _build_graph_client(config)

    try:
        drive_id = await _retry_on_transient(
            client, lambda: client.resolve_drive_id(req.library)
        )
        # Same force-refresh-on-deny pattern as upload — handles late-grant.
        result = await _gate_with_refresh_retry(
            client,
            lambda: client.create_folder(drive_id, req.parent_path, req.folder_name),
        )
    except ConnectorPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        if is_graph_permission_error(exc.response.status_code, exc.response.text):
            raise HTTPException(
                status_code=403,
                detail=graph_permission_error_message(
                    "Sites.ReadWrite.All",
                    operation="create folder",
                    graph_status=exc.response.status_code,
                    graph_body=exc.response.text,
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {exc!s}")

    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "webUrl": result.get("webUrl", ""),
        "message": f"Folder '{req.folder_name}' created successfully",
    }
