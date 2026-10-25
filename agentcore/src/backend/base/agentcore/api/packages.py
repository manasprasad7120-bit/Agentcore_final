"""Dependency governance API – read-only view of managed and transitive packages.

Data is synced from pyproject.toml + uv.lock into the database at application startup.
These endpoints simply read from the ``package`` table.

Endpoints:
    GET /packages/managed    – declared deps with resolved version
    GET /packages/transitive – transitive (indirect) deps with "required by" info
"""

from __future__ import annotations

from collections import defaultdict
from collections import deque
from datetime import date, datetime, timezone
import logging
import os
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import get_permissions_for_role
from agentcore.services.database.models.package.model import Package
from agentcore.services.database.models.package_request.model import PackageRequest
from agentcore.services.database.models.user.model import User
from agentcore.services.approval_notifications import notify_root_approvers, upsert_approval_notification

router = APIRouter(prefix="/packages", tags=["Packages"])
ACTIVE_END_DATE = date(9999, 12, 31)
DEFAULT_SERVICE_NAME = "all"
PACKAGE_REQUEST_STATUSES = {"PENDING", "APPROVED", "REJECTED", "DEPLOYED", "CANCELLED"}
logger = logging.getLogger(__name__)
_REGION_CODE = os.getenv("REGION_CODE", "").strip()
_REGION_GATEWAY_URL = os.getenv("REGION_GATEWAY_URL", "").strip()


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def _normalize_service_param(service: str | None) -> str:
    if not service:
        return DEFAULT_SERVICE_NAME
    return service.strip().lower()


def _is_all_services(service: str) -> bool:
    return service == "all"


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).strip().lower() == "root"


async def _require_package_permission(current_user: CurrentActiveUser, permission: str) -> None:
    if _is_root_user(current_user):
        return
    user_permissions = await get_permissions_for_role(str(current_user.role))
    if permission not in user_permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing required permissions.")


def _get_requested_region(request: Request) -> str | None:
    return request.headers.get("X-Region-Code", "").strip() or None


def _should_proxy_packages(request: Request, current_user: CurrentActiveUser) -> str | None:
    requested_region = _get_requested_region(request)
    if not requested_region or not _is_root_user(current_user):
        return None
    if not _REGION_GATEWAY_URL:
        raise HTTPException(status_code=500, detail="Region gateway is not configured.")
    if requested_region == _REGION_CODE:
        return None
    return requested_region


async def _proxy_package_json(
    *,
    request: Request,
    current_user: CurrentActiveUser,
    path: str,
    method: str = "GET",
    query_params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any | None:
    target_region = _should_proxy_packages(request, current_user)
    if not target_region:
        return None

    caller = str(getattr(current_user, "id", "") or "")
    base_url = _REGION_GATEWAY_URL.rstrip("/")
    target_path = path.lstrip("/")
    params = {k: v for k, v in (query_params or {}).items() if v is not None}
    if caller:
        params["caller"] = caller

    timeout = httpx.Timeout(60.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method.upper(),
                f"{base_url}/api/regions/{target_region}/{target_path}",
                params=params,
                json=json_body,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text or "Failed to proxy package request."
        if isinstance(detail, dict) and "detail" in detail:
            detail = detail["detail"]
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        logger.error("Package region proxy failed for %s: %s", target_region, exc)
        raise HTTPException(status_code=502, detail="Failed to reach target region.") from exc


class PackageRequestCreate(BaseModel):
    service_name: str = Field(min_length=2, max_length=100)
    package_name: str = Field(min_length=1, max_length=255)
    requested_version: str = Field(min_length=1, max_length=100)
    justification: str = Field(min_length=5, max_length=2000)


class PackageRequestAction(BaseModel):
    comments: str | None = Field(default=None, max_length=2000)


class PackageRequestDeploy(BaseModel):
    deployment_notes: str | None = Field(default=None, max_length=2000)


def _to_package_request_payload(
    row: PackageRequest,
    *,
    requested_by_user: User | None = None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "service_name": row.service_name,
        "package_name": row.package_name,
        "requested_version": row.requested_version,
        "justification": row.justification,
        "status": row.status.lower(),
        "requested_by": str(row.requested_by),
        "requested_by_name": requested_by_user.username if requested_by_user else None,
        "requested_by_email": requested_by_user.email if requested_by_user else None,
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "deployed_by": str(row.deployed_by) if row.deployed_by else None,
        "review_comments": row.review_comments,
        "deployment_notes": row.deployment_notes,
        "requested_at": row.requested_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "deployed_at": row.deployed_at.isoformat() if row.deployed_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _validate_status_filter(status_value: str | None) -> str | None:
    if not status_value:
        return None
    normalized = status_value.strip().upper()
    if normalized not in PACKAGE_REQUEST_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid package request status filter.")
    return normalized


async def _get_package_request_or_404(
    *,
    session: DbSession,
    request_id: str,
) -> PackageRequest:
    try:
        request_uuid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package request not found.") from exc
    row = await session.get(PackageRequest, request_uuid)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package request not found.")
    return row


@router.post("/requests")
async def create_package_request(
    payload: PackageRequestCreate,
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path="packages/requests",
        method="POST",
        json_body=payload.model_dump(),
    )
    if proxied is not None:
        return proxied
    await _require_package_permission(current_user, "request_packages")
    now = datetime.now(timezone.utc)
    row = PackageRequest(
        service_name=payload.service_name.strip().lower(),
        package_name=payload.package_name.strip().lower(),
        requested_version=payload.requested_version.strip(),
        justification=payload.justification.strip(),
        status="PENDING",
        requested_by=current_user.id,
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    await notify_root_approvers(
        session,
        entity_type="package_request",
        entity_id=str(row.id),
        title=f'Package "{row.package_name}" awaiting your approval.',
        link="/approval",
    )
    await session.commit()
    await session.refresh(row)
    requested_by_user = await session.get(User, row.requested_by)
    return _to_package_request_payload(row, requested_by_user=requested_by_user)


@router.get("/requests/mine")
async def get_my_package_requests(
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict[str, Any]]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path="packages/requests/mine",
    )
    if proxied is not None:
        return proxied
    rows = (
        await session.exec(
            select(PackageRequest)
            .where(PackageRequest.requested_by == current_user.id)
            .order_by(PackageRequest.requested_at.desc())
        )
    ).all()
    return [_to_package_request_payload(row, requested_by_user=current_user) for row in rows]


@router.get("/requests")
async def get_package_requests_for_root(
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path="packages/requests",
        query_params={"status": status},
    )
    if proxied is not None:
        return proxied
    if not _is_root_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only root users can view all package requests.",
        )

    stmt = select(PackageRequest).order_by(PackageRequest.requested_at.desc())
    normalized = _validate_status_filter(status)
    if normalized:
        stmt = stmt.where(PackageRequest.status == normalized)
    rows = (await session.exec(stmt)).all()
    requester_ids = {row.requested_by for row in rows}
    user_map: dict[Any, User] = {}
    if requester_ids:
        users = (await session.exec(select(User).where(User.id.in_(requester_ids)))).all()
        user_map = {user.id: user for user in users}
    return [
        _to_package_request_payload(row, requested_by_user=user_map.get(row.requested_by))
        for row in rows
    ]


@router.post("/requests/{request_id}/approve")
async def approve_package_request(
    request_id: str,
    payload: PackageRequestAction,
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path=f"packages/requests/{request_id}/approve",
        method="POST",
        json_body=payload.model_dump(),
    )
    if proxied is not None:
        return proxied
    if not _is_root_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only root users can approve package requests.")

    row = await _get_package_request_or_404(session=session, request_id=request_id)
    if row.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be approved.")

    now = datetime.now(timezone.utc)
    row.status = "APPROVED"
    row.reviewed_by = current_user.id
    row.reviewed_at = now
    row.review_comments = payload.comments.strip() if payload.comments else None
    row.updated_at = now
    session.add(row)
    if row.requested_by and row.requested_by != current_user.id:
        await upsert_approval_notification(
            session,
            recipient_user_id=row.requested_by,
            entity_type="package_request_result",
            entity_id=str(row.id),
            title=f'Package "{row.package_name}" was approved.',
            link="/approval",
        )
    await session.commit()
    await session.refresh(row)
    requested_by_user = await session.get(User, row.requested_by)
    return _to_package_request_payload(row, requested_by_user=requested_by_user)


@router.post("/requests/{request_id}/reject")
async def reject_package_request(
    request_id: str,
    payload: PackageRequestAction,
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path=f"packages/requests/{request_id}/reject",
        method="POST",
        json_body=payload.model_dump(),
    )
    if proxied is not None:
        return proxied
    if not _is_root_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only root users can reject package requests.")

    row = await _get_package_request_or_404(session=session, request_id=request_id)
    if row.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be rejected.")

    now = datetime.now(timezone.utc)
    row.status = "REJECTED"
    row.reviewed_by = current_user.id
    row.reviewed_at = now
    row.review_comments = payload.comments.strip() if payload.comments else None
    row.updated_at = now
    session.add(row)
    if row.requested_by and row.requested_by != current_user.id:
        await upsert_approval_notification(
            session,
            recipient_user_id=row.requested_by,
            entity_type="package_request_result",
            entity_id=str(row.id),
            title=f'Package "{row.package_name}" was rejected.',
            link="/approval",
        )
    await session.commit()
    await session.refresh(row)
    requested_by_user = await session.get(User, row.requested_by)
    return _to_package_request_payload(row, requested_by_user=requested_by_user)


@router.post("/requests/{request_id}/deploy")
async def deploy_package_request(
    request_id: str,
    payload: PackageRequestDeploy,
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path=f"packages/requests/{request_id}/deploy",
        method="POST",
        json_body=payload.model_dump(),
    )
    if proxied is not None:
        return proxied
    if not _is_root_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only root users can deploy package requests.")

    row = await _get_package_request_or_404(session=session, request_id=request_id)
    if row.status != "APPROVED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only approved requests can be deployed.")

    now = datetime.now(timezone.utc)
    row.status = "DEPLOYED"
    row.deployed_by = current_user.id
    row.deployed_at = now
    row.deployment_notes = payload.deployment_notes.strip() if payload.deployment_notes else None
    row.updated_at = now
    session.add(row)
    if row.requested_by and row.requested_by != current_user.id:
        await upsert_approval_notification(
            session,
            recipient_user_id=row.requested_by,
            entity_type="package_request_result",
            entity_id=str(row.id),
            title=f'Package "{row.package_name}" was deployed.',
            link="/approval",
        )
    await session.commit()
    await session.refresh(row)
    requested_by_user = await session.get(User, row.requested_by)
    return _to_package_request_payload(row, requested_by_user=requested_by_user)


@router.post("/requests/{request_id}/cancel")
async def cancel_package_request(
    request_id: str,
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any]:
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path=f"packages/requests/{request_id}/cancel",
        method="POST",
    )
    if proxied is not None:
        return proxied
    row = await _get_package_request_or_404(session=session, request_id=request_id)
    if row.requested_by != current_user.id and not _is_root_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to cancel this request.")
    if row.status not in {"PENDING"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be cancelled.")
    row.status = "CANCELLED"
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    requested_by_user = await session.get(User, row.requested_by)
    return _to_package_request_payload(row, requested_by_user=requested_by_user)


def _compute_managed_reachable_transitives(
    managed_names: set[str],
    transitive_rows: list[Package],
) -> set[str]:
    """Return transitive package names reachable from managed packages."""
    children_by_parent: dict[str, set[str]] = {}
    for row in transitive_rows:
        child = _normalize(row.name)
        parent_names: set[str] = set()
        for detail in row.required_by_details or []:
            parent = detail.get("name")
            if parent:
                parent_names.add(_normalize(parent))
        for parent in row.required_by or []:
            parent_names.add(_normalize(parent))
        for parent in parent_names:
            children_by_parent.setdefault(parent, set()).add(child)

    reachable: set[str] = set()
    queue = deque(managed_names)
    seen: set[str] = set(managed_names)
    while queue:
        parent = queue.popleft()
        for child in children_by_parent.get(parent, set()):
            if child in reachable:
                continue
            reachable.add(child)
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return reachable


def _build_parent_map(transitive_rows: list[Package]) -> dict[str, set[str]]:
    """Build child->parents map from transitive rows."""
    parents_by_child: dict[str, set[str]] = {}
    for row in transitive_rows:
        child = _normalize(row.name)
        parent_names: set[str] = set()
        for detail in row.required_by_details or []:
            parent = detail.get("name")
            if parent:
                parent_names.add(_normalize(parent))
        for parent in row.required_by or []:
            parent_names.add(_normalize(parent))
        if parent_names:
            parents_by_child.setdefault(child, set()).update(parent_names)
    return parents_by_child


def _compute_managed_root_data(
    transitive_name: str,
    parents_by_child: dict[str, set[str]],
    managed_names: set[str],
    display_names: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Return managed roots and human-readable dependency paths for one transitive package."""
    child = _normalize(transitive_name)
    roots: set[str] = set()
    paths: list[str] = []

    stack: list[tuple[str, list[str]]] = [(child, [child])]
    seen_states: set[tuple[str, tuple[str, ...]]] = set()
    max_paths = 25

    while stack and len(paths) < max_paths:
        node, upward_path = stack.pop()
        state = (node, tuple(upward_path))
        if state in seen_states:
            continue
        seen_states.add(state)

        for parent in parents_by_child.get(node, set()):
            if parent in upward_path:
                continue
            next_path = upward_path + [parent]
            if parent in managed_names:
                roots.add(parent)
                root_to_child = list(reversed(next_path))
                formatted = " -> ".join(display_names.get(name, name) for name in root_to_child)
                paths.append(formatted)
                continue
            stack.append((parent, next_path))

    root_list = sorted(display_names.get(name, name) for name in roots)
    unique_paths = list(dict.fromkeys(paths))
    return root_list, unique_paths


@router.get("/managed")
async def get_managed_packages(
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
    include_history: bool = Query(default=False),
    service: str = Query(default=DEFAULT_SERVICE_NAME),
) -> list[dict[str, Any]]:
    """Return declared dependencies with their resolved version."""
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path="packages/managed",
        query_params={
            "include_history": str(include_history).lower(),
            "service": service,
        },
    )
    if proxied is not None:
        return proxied
    normalized_service = _normalize_service_param(service)
    conditions = [Package.package_type == "managed"]
    if not _is_all_services(normalized_service):
        conditions.append(Package.service_name == normalized_service)
    if not include_history:
        conditions.append(Package.end_date == ACTIVE_END_DATE)

    rows = (
        await session.exec(
            select(Package)
            .where(*conditions)
            .order_by(Package.name.asc(), Package.start_date.desc(), Package.synced_at.desc())
        )
    ).all()

    return [
        {
            "id": str(row.id),
            "name": row.name,
            "version_spec": row.version_spec or "",
            "resolved_version": row.version,
            "service_name": row.service_name,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "is_current": row.end_date == ACTIVE_END_DATE,
            "source": row.source or {},
        }
        for row in rows
    ]


@router.get("/services")
async def get_package_services(
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
    include_history: bool = Query(default=False),
) -> list[str]:
    """Return distinct service names available in package snapshots."""
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path="packages/services",
        query_params={"include_history": str(include_history).lower()},
    )
    if proxied is not None:
        return proxied
    conditions = []
    if not include_history:
        conditions.append(Package.end_date == ACTIVE_END_DATE)

    rows = (
        await session.exec(
            select(Package.service_name)
            .where(*conditions)
            .distinct()
            .order_by(Package.service_name.asc())
        )
    ).all()
    services = [row[0] if isinstance(row, tuple) else row for row in rows]
    return [service for service in services if service]


@router.get("/transitive")
async def get_transitive_packages(
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
    include_history: bool = Query(default=False),
    include_full_graph: bool = Query(default=False),
    service: str = Query(default=DEFAULT_SERVICE_NAME),
) -> list[dict[str, Any]]:
    """Return transitive deps with strict managed-closure scope by default."""
    proxied = await _proxy_package_json(
        request=request,
        current_user=current_user,
        path="packages/transitive",
        query_params={
            "include_history": str(include_history).lower(),
            "include_full_graph": str(include_full_graph).lower(),
            "service": service,
        },
    )
    if proxied is not None:
        return proxied
    normalized_service = _normalize_service_param(service)
    conditions = [Package.package_type == "transitive"]
    if not _is_all_services(normalized_service):
        conditions.append(Package.service_name == normalized_service)
    if not include_history:
        conditions.append(Package.end_date == ACTIVE_END_DATE)

    rows = (
        await session.exec(
            select(Package)
            .where(*conditions)
            .order_by(Package.name.asc(), Package.start_date.desc(), Package.synced_at.desc())
        )
    ).all()

    current_managed_rows = (
        await session.exec(
            select(Package).where(*(
                [
                    Package.package_type == "managed",
                    Package.end_date == ACTIVE_END_DATE,
                ]
                + ([] if _is_all_services(normalized_service) else [Package.service_name == normalized_service])
            ))
        )
    ).all()

    current_transitive_rows = (
        await session.exec(
            select(Package).where(*(
                [
                    Package.package_type == "transitive",
                    Package.end_date == ACTIVE_END_DATE,
                ]
                + ([] if _is_all_services(normalized_service) else [Package.service_name == normalized_service])
            ))
        )
    ).all()
    managed_by_service: dict[str, list[Package]] = defaultdict(list)
    for pkg in current_managed_rows:
        managed_by_service[pkg.service_name].append(pkg)
    transitive_by_service: dict[str, list[Package]] = defaultdict(list)
    for pkg in current_transitive_rows:
        transitive_by_service[pkg.service_name].append(pkg)

    service_graph_data: dict[str, dict[str, Any]] = {}
    service_names = set(managed_by_service) | set(transitive_by_service)
    for service_name in service_names:
        service_managed_rows = managed_by_service.get(service_name, [])
        service_transitive_rows = transitive_by_service.get(service_name, [])
        managed_names = {_normalize(row.name) for row in service_managed_rows}
        reachable_transitives = _compute_managed_reachable_transitives(
            managed_names=managed_names,
            transitive_rows=service_transitive_rows,
        )
        parents_by_child = _build_parent_map(service_transitive_rows)
        display_names: dict[str, str] = {}
        for row in service_managed_rows:
            display_names[_normalize(row.name)] = row.name
        for row in service_transitive_rows:
            display_names[_normalize(row.name)] = row.name
        managed_lookup = {_normalize(pkg.name): pkg for pkg in service_managed_rows}
        service_graph_data[service_name] = {
            "managed_names": managed_names,
            "reachable_transitives": reachable_transitives,
            "parents_by_child": parents_by_child,
            "display_names": display_names,
            "managed_by_norm": managed_lookup,
        }

    response_rows: list[dict[str, Any]] = []
    for row in rows:
        graph_data = service_graph_data.get(
            row.service_name,
            {
                "managed_names": set(),
                "reachable_transitives": set(),
                "parents_by_child": {},
                "display_names": {},
                "managed_by_norm": {},
            },
        )
        normalized_name = _normalize(row.name)
        if not include_full_graph and normalized_name not in graph_data["reachable_transitives"]:
            continue

        managed_root_names, dependency_paths = _compute_managed_root_data(
            transitive_name=row.name,
            parents_by_child=graph_data["parents_by_child"],
            managed_names=graph_data["managed_names"],
            display_names=graph_data["display_names"],
        )
        root_order = {root: idx for idx, root in enumerate(managed_root_names)}
        dependency_paths = sorted(
            dependency_paths,
            key=lambda path: (
                root_order.get(path.split(" -> ", 1)[0], 10_000),
                path,
            ),
        )
        managed_root_details = []
        for root_name in managed_root_names:
            root_norm = _normalize(root_name)
            managed_pkg = graph_data["managed_by_norm"].get(root_norm)
            if managed_pkg is None:
                continue
            managed_root_details.append(
                {"name": managed_pkg.name, "version": managed_pkg.version}
            )

        response_rows.append(
            {
                "id": str(row.id),
                "name": row.name,
                "resolved_version": row.version,
                "service_name": row.service_name,
                # Backward-compatible fields (legacy UI support)
                "required_by": row.required_by or [],
                "required_by_details": row.required_by_details or [],
                # Strict governance fields
                "required_by_chain": managed_root_names,
                "required_by_chain_details": managed_root_details,
                "managed_roots": managed_root_names,
                "managed_root_details": managed_root_details,
                "dependency_paths": dependency_paths,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "is_current": row.end_date == ACTIVE_END_DATE,
                "scope": "full_graph" if include_full_graph else "managed_closure",
                "source": row.source or {},
            }
        )

    return response_rows
