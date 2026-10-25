"""REST endpoints for the MCP server registry.

All operations proxy through the MCP microservice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.mcp_service_client import (
    create_mcp_server_via_service,
    delete_mcp_server_via_service,
    fetch_mcp_servers_async,
    get_mcp_server_via_service,
    probe_mcp_server_via_service,
    test_mcp_connection_via_service,
    update_mcp_server_via_service,
)
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.mcp_registry.model import (
    McpProbeResponse,
    McpRegistry,
    McpRegistryCreate,
    McpRegistryRead,
    McpRegistryUpdate,
    McpTestConnectionRequest,
    McpTestConnectionResponse,
    McpToolInfo,
)
from agentcore.services.mcp_registry_service import apply_mcp_secret_refs
from agentcore.services.mcp_security import analyze as analyze_mcp_risk
from agentcore.services.database.models.mcp_approval_request.model import McpApprovalRequest
from agentcore.services.database.models.mcp_audit_log.model import McpAuditLog
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.role.model import Role
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.approval_notifications import upsert_approval_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/registry", tags=["MCP Registry"])


def _creator_display_name(display_name: str | None, email: str | None) -> str | None:
    name = str(display_name or "").strip()
    if name:
        return name
    normalized_email = str(email or "").strip()
    if not normalized_email:
        return None
    return normalized_email.split("@", 1)[0] if "@" in normalized_email else normalized_email


def _creator_email(email: str | None, username: str | None) -> str | None:
    normalized_email = str(email or "").strip()
    if normalized_email:
        return normalized_email
    normalized_username = str(username or "").strip()
    if normalized_username and "@" in normalized_username:
        return normalized_username
    return None


class McpRequestPayload(McpRegistryCreate):
    """Payload used by developer/business users to request MCP access."""


def _normalize_visibility(value: str | None) -> str:
    normalized = (value or "private").strip().lower()
    if normalized not in {"private", "public"}:
        raise HTTPException(status_code=400, detail=f"Unsupported visibility '{value}'")
    return normalized


def _normalize_public_scope(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"organization", "department"}:
        raise HTTPException(status_code=400, detail=f"Unsupported public_scope '{value}'")
    return normalized


def _normalize_environment(value: str | None) -> str:
    normalized = (value or "UAT").strip().lower()
    if normalized in {"test", "dev"}:
        normalized = "uat"
    if normalized not in {"uat", "prod"}:
        raise HTTPException(status_code=400, detail=f"Unsupported environment '{value}'")
    return normalized


def _normalize_environment_list(values: list[str] | None, fallback: str | None = None) -> list[str]:
    normalized = [_normalize_environment(v) for v in (values or []) if v is not None]
    if not normalized and fallback is not None:
        normalized = [_normalize_environment(fallback)]
    ordered: list[str] = []
    for env in ("uat", "prod"):
        if env in normalized and env not in ordered:
            ordered.append(env)
    for env in normalized:
        if env not in ordered:
            ordered.append(env)
    return ordered


def _resolve_mcp_environments(row: McpRegistry) -> list[str]:
    envs = [str(v).lower() for v in (getattr(row, "environments", None) or []) if v]
    if envs:
        return _normalize_environment_list(envs)
    return [_normalize_environment(getattr(row, "deployment_env", None))]


def _normalize_deployment_env(value: str | None) -> str:
    return _normalize_environment(value).upper()


def _string_ids(values: list[UUID] | None) -> list[str]:
    return [str(v) for v in (values or [])]


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


def _is_super_admin_user(current_user: CurrentActiveUser) -> bool:
    normalized = _normalize_role_variants(getattr(current_user, "role", ""))
    return bool(normalized.intersection({"super_admin", "superadmin"}))


def _normalize_role_variants(raw: str | None) -> set[str]:
    """Return a set of normalised role strings for flexible matching."""
    if not raw:
        return set()
    lowered = str(raw).strip().lower().replace(" ", "_")
    normalized = {lowered, lowered.replace("-", "_")}
    if "." in lowered:
        normalized.add(lowered.split(".")[-1].replace("-", "_"))
    normalized.add(normalize_role(raw))
    return normalized


def _can_self_approve(current_user: CurrentActiveUser) -> bool:
    """Return True if the user's role qualifies for self-approval fallback."""
    normalized = _normalize_role_variants(getattr(current_user, "role", ""))
    return bool(
        normalized.intersection(
            {
                "root",
                "super_admin",
                "department_admin",
            }
        )
    )


async def _append_mcp_audit(
    session: DbSession,
    *,
    mcp_id: UUID | None,
    actor_id: UUID | None,
    action: str,
    org_id: UUID | None = None,
    dept_id: UUID | None = None,
    deployment_env: str | None = None,
    visibility: str | None = None,
    details: dict | None = None,
    message: str | None = None,
) -> None:
    """Write one row to the mcp_audit_log table."""
    session.add(
        McpAuditLog(
            mcp_id=mcp_id,
            actor_id=actor_id,
            action=action,
            org_id=org_id,
            dept_id=dept_id,
            deployment_env=deployment_env,
            visibility=visibility,
            details=details,
            message=message,
        )
    )


async def _require_mcp_permission(current_user: CurrentActiveUser, permission: str) -> None:
    user_permissions = await get_permissions_for_role(str(current_user.role))
    if permission not in user_permissions:
        raise HTTPException(status_code=403, detail="Missing required permissions")


async def _require_any_mcp_permission(current_user: CurrentActiveUser, permissions: set[str]) -> None:
    user_permissions = set(await get_permissions_for_role(str(current_user.role)))
    if not user_permissions.intersection(permissions):
        raise HTTPException(status_code=403, detail="Missing required permissions")


async def _get_scope_memberships(session: DbSession, user_id: UUID) -> tuple[set[UUID], list[tuple[UUID, UUID]]]:
    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    return org_ids, [(row[0], row[1]) for row in dept_rows]


async def _resolve_user_primary_dept(
    session: DbSession, user_id: UUID | None
) -> tuple[UUID | None, UUID | None]:
    if not user_id:
        return None, None
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    if not dept_rows:
        return None, None
    org_id, dept_id = sorted(
        [(row[0], row[1]) for row in dept_rows], key=lambda x: (str(x[0]), str(x[1]))
    )[0]
    return org_id, dept_id


async def _validate_scope_refs(session: DbSession, org_id: UUID | None, dept_id: UUID | None) -> None:
    if dept_id and not org_id:
        raise HTTPException(status_code=400, detail="dept_id requires org_id")
    if org_id:
        org = await session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=400, detail="Invalid org_id")
    if dept_id:
        dept = (
            await session.exec(
                select(Department).where(Department.id == dept_id, Department.org_id == org_id)
            )
        ).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Invalid dept_id for org_id")



async def _validate_departments_exist_for_org(session: DbSession, org_id: UUID, dept_ids: list[UUID]) -> None:
    if not dept_ids:
        return
    rows = (
        await session.exec(select(Department.id).where(Department.org_id == org_id, Department.id.in_(dept_ids)))
    ).all()
    if len({str(r if isinstance(r, UUID) else r[0]) for r in rows}) != len({str(d) for d in dept_ids}):
        raise HTTPException(status_code=400, detail="One or more public_dept_ids are invalid for org_id")


async def _ensure_mcp_name_available(
    session: DbSession,
    server_name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(McpRegistry.id).where(
        func.lower(McpRegistry.server_name) == server_name.strip().lower(),
    )
    if exclude_id:
        stmt = stmt.where(McpRegistry.id != exclude_id)
    existing = (await session.exec(stmt)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="MCP server name already exists")


async def _test_mcp_connection_or_400(body: McpRegistryCreate) -> McpTestConnectionResponse:
    payload = {
        "mode": body.mode,
        "url": body.url,
        "command": body.command,
        "args": body.args,
        "env_vars": body.env_vars,
        "headers": body.headers,
    }
    result = await test_mcp_connection_via_service(payload)
    if not result or not result.get("success"):
        message = result.get("message") if isinstance(result, dict) else None
        raise HTTPException(status_code=400, detail=message or "MCP test connection failed")
    return McpTestConnectionResponse(**result)


def _prepare_mcp_service_payload(payload: dict) -> dict:
    """Align payload keys for MCP microservice compatibility."""
    if payload.get("server_name") and not payload.get("name"):
        payload["name"] = payload["server_name"]
    return payload


def _normalize_tools_snapshot(tools: list | None) -> list[dict] | None:
    if not tools:
        return None
    normalized: list[dict] = []
    for tool in tools:
        if isinstance(tool, dict):
            normalized.append(tool)
        else:
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", None)
            if name is not None:
                normalized.append({"name": name, "description": description or ""})
    return normalized or None


async def _enforce_creation_scope(
    session: DbSession,
    current_user: CurrentActiveUser,
    payload: McpRegistryCreate | McpRegistryUpdate,
) -> tuple[str, str | None, list[str], list[str]]:
    user_role = normalize_role(str(current_user.role))
    visibility = _normalize_visibility(getattr(payload, "visibility", None))
    public_scope = _normalize_public_scope(getattr(payload, "public_scope", None))
    public_dept_ids = _string_ids(getattr(payload, "public_dept_ids", None))
    shared_user_ids: list[str] = []
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)

    if user_role not in {"root", "super_admin", "department_admin", "developer", "business_user"}:
        raise HTTPException(status_code=403, detail="Your role is not allowed to manage MCP servers")

    if visibility == "private":
        payload.public_scope = None
        payload.public_dept_ids = None
        if user_role == "root":
            payload.org_id = None
            payload.dept_id = None
        elif user_role == "super_admin":
            if payload.org_id and payload.org_id in org_ids:
                payload.dept_id = None
            else:
                if not org_ids:
                    raise HTTPException(status_code=403, detail="No active organization scope found")
                payload.org_id = sorted(org_ids, key=str)[0]
                payload.dept_id = None
        elif payload.org_id and payload.dept_id:
            if user_role in {"department_admin", "developer", "business_user"}:
                if not any(payload.org_id == org_id and payload.dept_id == dept_id for org_id, dept_id in dept_pairs):
                    raise HTTPException(
                        status_code=403,
                        detail="Private visibility must stay within your department scope",
                    )
        elif dept_pairs:
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            payload.org_id = current_org_id
            payload.dept_id = current_dept_id
        elif user_role in {"developer", "business_user", "department_admin"}:
            raise HTTPException(status_code=403, detail="No active department scope found")
    else:
        if public_scope is None:
            raise HTTPException(status_code=400, detail="public_scope is required when visibility is public")
        if public_scope == "organization":
            if not payload.org_id:
                raise HTTPException(status_code=400, detail="org_id is required for public organization visibility")
            if user_role != "root" and payload.org_id not in org_ids:
                raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
            payload.dept_id = None
            payload.public_dept_ids = None
            public_dept_ids = []
        else:
            if user_role in {"super_admin", "root"}:
                if not payload.org_id:
                    raise HTTPException(status_code=400, detail="org_id is required for department visibility")
                if user_role != "root" and payload.org_id not in org_ids:
                    raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
                if not public_dept_ids and payload.dept_id:
                    public_dept_ids = [str(payload.dept_id)]
                if not public_dept_ids:
                    raise HTTPException(status_code=400, detail="Select at least one department")
                await _validate_departments_exist_for_org(session, payload.org_id, [UUID(v) for v in public_dept_ids])
                payload.dept_id = UUID(public_dept_ids[0]) if len(public_dept_ids) == 1 else None
            else:
                if not dept_pairs:
                    raise HTTPException(status_code=403, detail="No active department scope found")
                current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
                payload.org_id = current_org_id
                payload.dept_id = current_dept_id
                public_dept_ids = [str(current_dept_id)]
        shared_user_ids = []

    await _validate_scope_refs(session, payload.org_id, payload.dept_id)
    return visibility, public_scope, public_dept_ids, shared_user_ids


def _can_access_server(
    row: McpRegistry,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return True

    role = normalize_role(str(current_user.role))
    if role == "super_admin" and row.org_id and row.org_id in org_ids:
        return True

    # Department admin bypass: see everything in their departments (matches model registry).
    if role == "department_admin":
        dept_id_set = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if row.dept_id and str(row.dept_id) in dept_id_set:
            return True
        if scoped_public_depts.intersection(dept_id_set):
            return True

    # Keep requester/approver visibility for pending/rejected requests.
    if (row.approval_status or "approved") != "approved":
        return row.requested_by == current_user.id or row.request_to == current_user.id

    visibility = _normalize_visibility(getattr(row, "visibility", "private"))
    user_id = str(current_user.id)
    dept_id_set = {str(dept_id) for _, dept_id in dept_pairs}

    if visibility == "private":
        if role == "department_admin":
            return bool(row.dept_id and str(row.dept_id) in dept_id_set)
        return (
            str(row.created_by_id) == user_id
            or row.created_by == getattr(current_user, "username", None)
        )
    if getattr(row, "public_scope", None) == "organization":
        return bool(row.org_id and row.org_id in org_ids)
    if getattr(row, "public_scope", None) == "department":
        dept_candidates = set(row.public_dept_ids or [])
        if row.dept_id:
            dept_candidates.add(str(row.dept_id))
        return bool(dept_candidates.intersection(dept_id_set))
    return False


async def _resolve_request_approver(
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> UUID:
    # Requests are always routed to department admin from requester's department.
    target_dept_id = dept_id
    if not target_dept_id:
        _, dept_pairs = await _get_scope_memberships(session, current_user.id)
        if not dept_pairs:
            raise HTTPException(status_code=403, detail="No active department scope found for requester")
        _, target_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
    dept = await session.get(Department, target_dept_id)
    if not dept or not dept.admin_user_id:
        raise HTTPException(status_code=400, detail="No department admin configured for requester department")
    return dept.admin_user_id


async def _resolve_super_admin_approver(
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None,
) -> UUID:
    resolved_org_id = org_id
    if not resolved_org_id:
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        resolved_org_id = next(iter(org_ids), None)

    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="No organization scope available for approval routing")

    stmt = (
        select(User)
        .join(UserOrganizationMembership, UserOrganizationMembership.user_id == User.id)
        .join(Role, Role.id == UserOrganizationMembership.role_id)
        .where(
            UserOrganizationMembership.org_id == resolved_org_id,
            UserOrganizationMembership.status == "active",
            func.lower(Role.name) == "super_admin",
            User.id != current_user.id,
        )
        .order_by(User.create_at.asc())
    )
    row = (await session.exec(stmt)).first()
    if not row:
        if _can_self_approve(current_user):
            return current_user.id
        raise HTTPException(status_code=400, detail="No Super Admin approver available")
    return row.id


def _requires_super_admin_mcp_approval(*, deployment_env: str, visibility: str, public_scope: str | None) -> bool:
    normalized_visibility = _normalize_visibility(visibility)
    normalized_public_scope = _normalize_public_scope(public_scope)
    return normalized_visibility == "public" and normalized_public_scope == "organization"


def _is_department_scoped_mcp(row: McpRegistry, dept_pairs: list[tuple[UUID, UUID]]) -> bool:
    user_dept_ids = {str(dept_id) for _, dept_id in dept_pairs}
    mcp_dept_ids = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
    if row.dept_id:
        mcp_dept_ids.add(str(row.dept_id))
    return bool(mcp_dept_ids.intersection(user_dept_ids))


def _is_multi_dept_mcp(row: McpRegistry) -> bool:
    return len(list(getattr(row, "public_dept_ids", None) or [])) > 1


def _can_edit_mcp(
    row: McpRegistry,
    current_user: CurrentActiveUser,
    *,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user) or _is_super_admin_user(current_user):
        return True
    normalized_roles = _normalize_role_variants(getattr(current_user, "role", ""))
    user_id = str(current_user.id)
    visibility = _normalize_visibility(getattr(row, "visibility", None))
    public_scope = _normalize_public_scope(getattr(row, "public_scope", None))
    dept_ids = {str(d) for _, d in dept_pairs}
    scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}

    if normalized_roles.intersection({"department_admin"}):
        if _is_multi_dept_mcp(row):
            return False
        if visibility == "public" and public_scope == "organization":
            return False
        if visibility == "public" and public_scope == "department":
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
            if scoped_public_depts.intersection(dept_ids):
                return True
        if visibility == "private":
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
        reviewed_by = str(getattr(row, "reviewed_by", "") or "")
        if reviewed_by == user_id:
            return True
        if not reviewed_by:
            return str(getattr(row, "created_by_id", "") or "") == user_id and (row.approval_status or "approved") == "approved"
    return False


def _can_delete_mcp(
    row: McpRegistry,
    current_user: CurrentActiveUser,
    *,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return True
    if not row.org_id:
        return False

    normalized_roles = _normalize_role_variants(getattr(current_user, "role", ""))
    user_id = str(current_user.id)
    if normalized_roles.intersection({"developer", "business_user"}):
        return False
    if normalized_roles.intersection({"super_admin", "superadmin"}):
        return bool(row.org_id and row.org_id in org_ids)
    if normalized_roles.intersection({"department_admin"}):
        if _is_multi_dept_mcp(row):
            return False
        visibility = _normalize_visibility(getattr(row, "visibility", None))
        public_scope = _normalize_public_scope(getattr(row, "public_scope", None))
        if visibility == "public" and public_scope == "organization":
            return False
        dept_ids = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if visibility == "public" and public_scope == "department":
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
            if scoped_public_depts.intersection(dept_ids):
                return True
        if visibility == "private" and row.dept_id and str(row.dept_id) in dept_ids:
            return True
        reviewed_by = str(getattr(row, "reviewed_by", "") or "")
        if reviewed_by == user_id:
            return True
        if not reviewed_by:
            return str(getattr(row, "created_by_id", "") or "") == user_id and (row.approval_status or "approved") == "approved"
    return False


@router.get("/", response_model=list[McpRegistryRead])
async def list_mcp_servers(
    session: DbSession,
    current_user: CurrentActiveUser,
    active_only: bool = False,
):
    """List MCP servers visible to the current user based on tenancy + approval state."""
    await _require_mcp_permission(current_user, "view_mcp_page")

    raw_rows = await fetch_mcp_servers_async(active_only=active_only)
    ids = [UUID(r["id"]) for r in raw_rows if isinstance(r, dict) and r.get("id")]
    tools_map: dict[str, dict] = {}
    if ids:
        rows = (
            await session.exec(
                select(
                    McpRegistry.id,
                    McpRegistry.tools_count,
                    McpRegistry.tools_checked_at,
                    McpRegistry.tools_snapshot,
                ).where(
                    McpRegistry.id.in_(ids)
                )
            )
        ).all()
        tools_map = {
            str(r[0]): {"tools_count": r[1], "tools_checked_at": r[2], "tools_snapshot": r[3]} for r in rows
        }
        creator_rows = (
            await session.exec(
                select(McpRegistry.id, McpRegistry.created_by_id, McpRegistry.created_by).where(McpRegistry.id.in_(ids))
            )
        ).all()
        creator_ids = [row[1] for row in creator_rows if row[1]]
        creator_identities = {
            str(row[2]).strip().lower()
            for row in creator_rows
            if row[2] and str(row[2]).strip()
        }
        creator_lookup: dict[str, dict[str, str | None]] = {}
        if creator_ids:
            user_rows = (
                await session.exec(
                    select(User.id, User.display_name, User.email, User.username).where(User.id.in_(creator_ids))
                )
            ).all()
            creator_lookup = {
                str(row[0]): {
                    "display": _creator_display_name(row[1], row[2]),
                    "email": _creator_email(row[2], row[3]),
                }
                for row in user_rows
            }
        creator_identity_lookup: dict[str, dict[str, str | None]] = {}
        if creator_identities:
            identity_rows = (
                await session.exec(
                    select(User.display_name, User.email, User.username).where(
                        func.lower(func.coalesce(User.email, User.username)).in_(list(creator_identities))
                    )
                )
            ).all()
            creator_identity_lookup = {
                str(row[1] or row[2]).strip().lower(): {
                    "display": _creator_display_name(row[0], row[1]),
                    "email": _creator_email(row[1], row[2]),
                }
                for row in identity_rows
                if str(row[1] or row[2]).strip()
            }
        mcp_creator_by_id = {
            str(row[0]): (
                creator_lookup.get(str(row[1]))
                if row[1]
                else creator_identity_lookup.get(str(row[2]).strip().lower()) if row[2] else None
            )
            for row in creator_rows
        }
    else:
        mcp_creator_by_id = {}
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    visible = []
    for r in raw_rows:
        try:
            server_obj = McpRegistry.model_validate(r)
            if _can_access_server(server_obj, current_user, org_ids, dept_pairs):
                if isinstance(r, dict):
                    extras = tools_map.get(str(r.get("id")), {})
                    if extras:
                        r["tools_count"] = extras.get("tools_count")
                        r["tools_checked_at"] = extras.get("tools_checked_at")
                        r["tools_snapshot"] = extras.get("tools_snapshot")
                    creator_meta = mcp_creator_by_id.get(str(r.get("id")))
                    if creator_meta:
                        r["created_by"] = creator_meta.get("display") or r.get("created_by")
                        r["created_by_email"] = creator_meta.get("email")
                visible.append(r)
        except Exception:
            continue
    visible.sort(
        key=lambda item: (
            str(
                item.get("server_name")
                if isinstance(item, dict)
                else getattr(item, "server_name", "")
            ).strip().lower()
        )
    )
    return visible


@router.get("/visibility-options")
async def get_mcp_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_mcp_permission(current_user, "view_mcp_page")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    role = normalize_role(str(current_user.role))

    organizations = []
    if role == "root":
        org_rows = (
            await session.exec(
                select(Organization.id, Organization.name).where(Organization.status == "active")
            )
        ).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]
    elif org_ids:
        org_rows = (
            await session.exec(
                select(Organization.id, Organization.name).where(
                    Organization.id.in_(list(org_ids)),
                    Organization.status == "active",
                )
            )
        ).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]

    dept_ids = {dept_id for _, dept_id in dept_pairs}
    departments = []
    if role == "root":
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(Department.status == "active")
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]
    elif role == "super_admin" and org_ids:
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(
                    Department.org_id.in_(list(org_ids)),
                    Department.status == "active",
                )
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]
    elif dept_ids:
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(
                    Department.id.in_(list(dept_ids)),
                    Department.status == "active",
                )
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]

    return {
        "organizations": organizations,
        "departments": departments,
        "role": role,
    }


@router.post("/", response_model=McpRegistryRead, status_code=201)
async def create_mcp_server(
    body: McpRegistryCreate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Register a new MCP server directly (admin flows)."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "add_new_mcp")

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(session, current_user, body)
    await _ensure_mcp_name_available(session, body.server_name)
    normalized_envs = _normalize_environment_list(
        getattr(body, "environments", None),
        getattr(body, "deployment_env", None),
    )
    body.environments = normalized_envs or ["uat"]
    body.deployment_env = _normalize_deployment_env(body.environments[0])
    now = datetime.now(timezone.utc)
    test_result = await _test_mcp_connection_or_400(body)
    user_role = normalize_role(str(current_user.role))
    body.visibility = visibility
    body.public_scope = public_scope
    body.public_dept_ids = [UUID(v) for v in public_dept_ids] if public_dept_ids else None
    body.shared_user_ids = shared_user_ids
    body.created_by = current_user.username
    body.created_by_id = current_user.id
    body.requested_by = current_user.id
    body.requested_at = now
    requires_super_admin = _requires_super_admin_mcp_approval(
        deployment_env=body.deployment_env,
        visibility=visibility,
        public_scope=public_scope,
    )
    auto_approve = user_role in {"root", "super_admin"} or (
        user_role == "department_admin" and not requires_super_admin
    )

    if auto_approve:
        body.request_to = None
        body.reviewed_at = now
        body.reviewed_by = current_user.id
        body.approval_status = "approved"
        body.is_active = True
        body.status = "connected"
        service_payload = _prepare_mcp_service_payload(body.model_dump(mode="json"))
        service_payload.pop("environments", None)
        created_dict = await create_mcp_server_via_service(service_payload)
        created_row = await session.get(McpRegistry, UUID(created_dict["id"]))
        if created_row and body.environments:
            created_row.environments = body.environments
            created_row.deployment_env = body.deployment_env
        if created_row:
            created_row.tools_count = test_result.tools_count
            created_row.tools_checked_at = now
            created_row.tools_snapshot = _normalize_tools_snapshot(test_result.tools)
        if isinstance(created_dict, dict):
            created_dict["tools_count"] = test_result.tools_count
            created_dict["tools_checked_at"] = now
            created_dict["tools_snapshot"] = _normalize_tools_snapshot(test_result.tools)
        if created_row and (body.env_vars is not None or body.headers is not None):
            apply_mcp_secret_refs(created_row, env_vars=body.env_vars, headers=body.headers)
            session.add(created_row)
        await _append_mcp_audit(
            session,
            mcp_id=UUID(created_dict["id"]),
            actor_id=current_user.id,
            action="mcp.create.auto_approved",
            org_id=body.org_id,
            dept_id=body.dept_id,
            deployment_env=body.deployment_env,
            visibility=visibility,
            details={"auto_approved": True, "reason": "admin_create"},
            message="MCP server created and auto-approved by admin",
        )
        await session.commit()
        return created_dict

    approver_id = await _resolve_super_admin_approver(session, current_user, body.org_id)
    body.request_to = approver_id
    body.reviewed_at = None
    body.reviewed_by = None
    body.approval_status = "pending"
    body.is_active = False
    body.status = "pending_approval"
    service_payload = _prepare_mcp_service_payload(body.model_dump(mode="json"))
    service_payload.pop("environments", None)
    created_dict = await create_mcp_server_via_service(service_payload)
    created_row = await session.get(McpRegistry, UUID(created_dict["id"]))
    if created_row and body.environments:
        created_row.environments = body.environments
        created_row.deployment_env = body.deployment_env
        if created_row:
            created_row.tools_count = test_result.tools_count
            created_row.tools_checked_at = now
            created_row.tools_snapshot = _normalize_tools_snapshot(test_result.tools)
        if isinstance(created_dict, dict):
            created_dict["tools_count"] = test_result.tools_count
            created_dict["tools_checked_at"] = now
            created_dict["tools_snapshot"] = _normalize_tools_snapshot(test_result.tools)
    if created_row and (body.env_vars is not None or body.headers is not None):
        apply_mcp_secret_refs(created_row, env_vars=body.env_vars, headers=body.headers)
        session.add(created_row)
    created_id = UUID(created_dict["id"])

    approval = McpApprovalRequest(
        mcp_id=created_id,
        org_id=body.org_id,
        dept_id=body.dept_id,
        requested_by=current_user.id,
        request_to=approver_id,
        requested_at=now,
        deployment_env=body.deployment_env,
        requested_environments=body.environments,
    )
    session.add(approval)
    await upsert_approval_notification(
        session,
        recipient_user_id=approver_id,
        entity_type="mcp_request",
        entity_id=str(approval.id),
        title=f'MCP server "{body.server_name}" awaiting your approval.',
        link="/approval",
    )
    await _append_mcp_audit(
        session,
        mcp_id=created_id,
        actor_id=current_user.id,
        action="mcp.create.requested",
        org_id=body.org_id,
        dept_id=body.dept_id,
        deployment_env=body.deployment_env,
        visibility=visibility,
        details={"request_to": str(approver_id)},
        message="MCP server creation pending approval",
    )
    await session.commit()
    return created_dict


@router.post("/request", response_model=McpRegistryRead, status_code=201)
async def request_mcp_server(
    body: McpRequestPayload,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Request a new MCP server (developer/business_user flows)."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "request_new_mcp")
    role = normalize_role(str(current_user.role))
    if role not in {"developer", "business_user"}:
        raise HTTPException(status_code=403, detail="Only developer/business_user can create MCP requests")

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(session, current_user, body)
    await _ensure_mcp_name_available(session, body.server_name)
    normalized_envs = _normalize_environment_list(
        getattr(body, "environments", None),
        getattr(body, "deployment_env", None),
    )
    deployment_env = _normalize_deployment_env((normalized_envs or ["uat"])[0])
    now = datetime.now(timezone.utc)
    test_result = await _test_mcp_connection_or_400(body)

    body.environments = normalized_envs or ["uat"]
    body.deployment_env = deployment_env
    body.visibility = visibility
    body.public_scope = public_scope
    body.public_dept_ids = [UUID(v) for v in public_dept_ids] if public_dept_ids else None
    body.shared_user_ids = shared_user_ids
    body.created_by = current_user.username
    body.created_by_id = current_user.id
    body.requested_by = current_user.id
    body.requested_at = now

    if _requires_super_admin_mcp_approval(
        deployment_env=deployment_env,
        visibility=visibility,
        public_scope=public_scope,
    ):
        approver_id = await _resolve_super_admin_approver(session, current_user, body.org_id)
    else:
        approver_id = await _resolve_request_approver(session, current_user, body.org_id, body.dept_id)
    body.request_to = approver_id
    body.reviewed_at = None
    body.reviewed_by = None
    body.approval_status = "pending"
    body.is_active = False
    body.status = "pending_approval"
    service_payload = _prepare_mcp_service_payload(body.model_dump(mode="json"))
    service_payload.pop("environments", None)
    created_dict = await create_mcp_server_via_service(service_payload)
    created_row = await session.get(McpRegistry, UUID(created_dict["id"]))
    if created_row and body.environments:
        created_row.environments = body.environments
        created_row.deployment_env = body.deployment_env
    if created_row:
        created_row.tools_count = test_result.tools_count
        created_row.tools_checked_at = now
        created_row.tools_snapshot = _normalize_tools_snapshot(test_result.tools)
    if isinstance(created_dict, dict):
        created_dict["tools_count"] = test_result.tools_count
        created_dict["tools_checked_at"] = now
        created_dict["tools_snapshot"] = _normalize_tools_snapshot(test_result.tools)
    if created_row and (body.env_vars is not None or body.headers is not None):
        apply_mcp_secret_refs(created_row, env_vars=body.env_vars, headers=body.headers)
        session.add(created_row)
    created_id = UUID(created_dict["id"])

    approval = McpApprovalRequest(
        mcp_id=created_id,
        org_id=body.org_id,
        dept_id=body.dept_id,
        requested_by=current_user.id,
        request_to=approver_id,
        requested_at=now,
        deployment_env=deployment_env,
        requested_environments=body.environments,
    )
    session.add(approval)
    await upsert_approval_notification(
        session,
        recipient_user_id=approver_id,
        entity_type="mcp_request",
        entity_id=str(approval.id),
        title=f'MCP server "{body.server_name}" awaiting your approval.',
        link="/approval",
    )
    await _append_mcp_audit(
        session,
        mcp_id=created_id,
        actor_id=current_user.id,
        action="mcp.request.requested",
        org_id=body.org_id,
        dept_id=body.dept_id,
        deployment_env=deployment_env,
        visibility=visibility,
        details={"request_to": str(approver_id)},
        message="MCP server request pending approval",
    )
    await session.commit()
    return created_dict


@router.get("/{server_id}", response_model=McpRegistryRead)
async def get_mcp_server(
    server_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Get a single MCP server by ID."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    server_dict = await get_mcp_server_via_service(str(server_id))
    if server_dict is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    # RBAC check using local DB row
    server = await session.get(McpRegistry, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(server, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    if isinstance(server_dict, dict):
        server_dict["tools_count"] = server.tools_count
        server_dict["tools_checked_at"] = server.tools_checked_at
        server_dict["tools_snapshot"] = server.tools_snapshot
    return server_dict


@router.put("/{server_id}", response_model=McpRegistryRead)
async def update_mcp_server(
    server_id: UUID,
    body: McpRegistryUpdate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Update an existing MCP server."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "edit_mcp")
    row = await session.get(McpRegistry, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    if not _can_edit_mcp(row, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="You do not have permission to edit this MCP server")

    if body.org_id is None:
        body.org_id = row.org_id
    if body.dept_id is None and body.public_scope != "organization":
        body.dept_id = row.dept_id
    if body.visibility is None:
        body.visibility = row.visibility
    if body.public_scope is None:
        body.public_scope = row.public_scope
    if body.public_dept_ids is None:
        body.public_dept_ids = [UUID(v) for v in (row.public_dept_ids or [])]

    current_envs = _resolve_mcp_environments(row)
    if body.environments is not None:
        desired_envs = _normalize_environment_list(body.environments)
        if desired_envs != current_envs:
            raise HTTPException(status_code=400, detail="Direct environment change is blocked. Use approval flow")
        body.environments = desired_envs

    if body.deployment_env is None:
        body.deployment_env = row.deployment_env
    else:
        normalized_env = _normalize_deployment_env(body.deployment_env)
        if normalized_env.lower() not in current_envs:
            raise HTTPException(status_code=400, detail="Direct environment change is blocked. Use approval flow")
        body.deployment_env = normalized_env

    if body.visibility == "private" and body.dept_id is None:
        current_role = normalize_role(str(current_user.role))
        if current_role in {"department_admin", "developer", "business_user"} and dept_pairs:
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            if body.org_id is None:
                body.org_id = current_org_id
            body.dept_id = current_dept_id
        else:
            owner_id = row.created_by_id or row.requested_by
            owner_org_id, owner_dept_id = await _resolve_user_primary_dept(session, owner_id)
            if owner_org_id and body.org_id is None:
                body.org_id = owner_org_id
            if owner_dept_id:
                body.dept_id = owner_dept_id

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(session, current_user, body)
    if body.server_name:
        await _ensure_mcp_name_available(session, body.server_name, exclude_id=server_id)
    body.visibility = visibility
    body.public_scope = public_scope
    body.public_dept_ids = [UUID(v) for v in public_dept_ids] if public_dept_ids else None
    body.shared_user_ids = shared_user_ids
    body.reviewed_by = row.reviewed_by
    body.requested_by = row.requested_by
    body.request_to = row.request_to
    if visibility == "private":
        body.created_by = current_user.username
        body.created_by_id = current_user.id

    current_public_dept_ids = [str(v) for v in (row.public_dept_ids or [])]
    desired_public_dept_ids = [str(v) for v in (body.public_dept_ids or [])]
    visibility_changed = (
        visibility != _normalize_visibility(row.visibility)
        or public_scope != _normalize_public_scope(row.public_scope)
        or (row.org_id or None) != (body.org_id or None)
        or (row.dept_id or None) != (body.dept_id or None)
        or sorted(current_public_dept_ids) != sorted(desired_public_dept_ids)
    )

    if visibility_changed:
        if _is_root_user(current_user) or _is_super_admin_user(current_user):
            approver_id = current_user.id
        else:
            approver_id = await _resolve_super_admin_approver(session, current_user, body.org_id) if _requires_super_admin_mcp_approval(
                deployment_env=row.deployment_env,
                visibility=visibility,
                public_scope=public_scope,
            ) else await _resolve_request_approver(session, current_user, body.org_id, body.dept_id)

        if approver_id == current_user.id and _can_self_approve(current_user):
            service_payload = _prepare_mcp_service_payload(
                body.model_dump(mode="json", exclude_unset=True)
            )
            service_payload.pop("environments", None)
            server_dict = await update_mcp_server_via_service(str(server_id), service_payload)
            if server_dict is None:
                raise HTTPException(status_code=404, detail="MCP server not found")
            if body.env_vars is not None or body.headers is not None:
                apply_mcp_secret_refs(row, env_vars=body.env_vars, headers=body.headers)
                session.add(row)
            await _append_mcp_audit(
                session,
                mcp_id=server_id,
                actor_id=current_user.id,
                action="mcp.updated.auto_approved",
                org_id=body.org_id,
                dept_id=body.dept_id,
                deployment_env=body.deployment_env,
                visibility=visibility,
                details={"auto_approved": True},
                message="MCP server updated and auto-approved",
            )
            await session.commit()
            return server_dict

        now = datetime.now(timezone.utc)
        row.approval_status = "pending"
        row.requested_by = current_user.id
        row.request_to = approver_id
        row.requested_at = now
        row.reviewed_at = None
        row.reviewed_by = None
        row.status = "pending_approval"
        row.updated_at = now
        session.add(row)

        approval = McpApprovalRequest(
            mcp_id=server_id,
            org_id=body.org_id,
            dept_id=body.dept_id,
            requested_by=current_user.id,
            request_to=approver_id,
            requested_at=now,
            deployment_env=row.deployment_env,
            requested_environments=_resolve_mcp_environments(row),
            requested_visibility=visibility,
            requested_public_scope=public_scope,
            requested_org_id=body.org_id,
            requested_dept_id=body.dept_id,
            requested_public_dept_ids=desired_public_dept_ids or None,
        )
        session.add(approval)
        await upsert_approval_notification(
            session,
            recipient_user_id=approver_id,
            entity_type="mcp_request",
            entity_id=str(approval.id),
            title=f'MCP server "{row.server_name}" awaiting your approval.',
            link="/approval",
        )
        await _append_mcp_audit(
            session,
            mcp_id=server_id,
            actor_id=current_user.id,
            action="mcp.visibility.requested",
            org_id=body.org_id,
            dept_id=body.dept_id,
            deployment_env=row.deployment_env,
            visibility=visibility,
            details={"request_to": str(approver_id)},
            message="MCP visibility change pending approval",
        )
        await session.commit()
        return McpRegistryRead.from_orm_model(row)

    service_payload = _prepare_mcp_service_payload(
        body.model_dump(mode="json", exclude_unset=True)
    )
    service_payload.pop("environments", None)
    server_dict = await update_mcp_server_via_service(str(server_id), service_payload)
    if server_dict is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if body.env_vars is not None or body.headers is not None:
        apply_mcp_secret_refs(row, env_vars=body.env_vars, headers=body.headers)
        session.add(row)
    await _append_mcp_audit(
        session,
        mcp_id=server_id,
        actor_id=current_user.id,
        action="mcp.updated",
        org_id=body.org_id,
        dept_id=body.dept_id,
        deployment_env=body.deployment_env,
        visibility=visibility,
        message="MCP server updated",
    )
    await session.commit()
    return server_dict


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Delete a registered MCP server."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "delete_mcp")
    row = await session.get(McpRegistry, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    if not _can_delete_mcp(row, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="You do not have permission to delete this MCP server")
    # Clean up any local approval requests before deleting via microservice
    approval_rows = (
        await session.exec(
            select(McpApprovalRequest).where(McpApprovalRequest.mcp_id == server_id)
        )
    ).all()
    for ar in approval_rows:
        await session.delete(ar)

    # Null-out mcp_id on existing audit rows so the FK doesn't block deletion
    audit_rows = (
        await session.exec(
            select(McpAuditLog).where(McpAuditLog.mcp_id == server_id)
        )
    ).all()
    for audit in audit_rows:
        audit.mcp_id = None
        session.add(audit)

    await _append_mcp_audit(
        session,
        mcp_id=None,
        actor_id=current_user.id,
        action="mcp.deleted",
        org_id=row.org_id,
        dept_id=row.dept_id,
        deployment_env=row.deployment_env,
        visibility=row.visibility,
        details={"deleted_mcp_id": str(server_id)},
        message="MCP server deleted",
    )
    await session.commit()

    deleted = await delete_mcp_server_via_service(str(server_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP server not found")


@router.post("/test-connection", response_model=McpTestConnectionResponse)
async def test_mcp_connection(
    body: McpTestConnectionRequest,
    current_user: CurrentActiveUser,
):
    """Test connectivity to an MCP server and return the number of tools discovered.

    Restricted to MCP admins (`add_new_mcp` permission). Developers and business users
    submit MCP requests for admin review; admins run Test Connection during review.
    Test connection spawns a subprocess (STDIO mode) or opens an outbound connection
    (SSE mode) using raw, un-vetted form input, so it must not be reachable by the
    request-only roles.
    """
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "add_new_mcp")
    try:
        result = await test_mcp_connection_via_service(body.model_dump(mode="json"))
        return McpTestConnectionResponse(**result)
    except Exception as e:
        logger.warning("MCP test connection via microservice failed: %s", e)
        return McpTestConnectionResponse(success=False, message=str(e))


class McpRiskAnalyzeRequest(BaseModel):
    mode: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env_vars: dict[str, str] | None = None
    headers: dict[str, str] | None = None


class McpRiskFinding(BaseModel):
    category: str
    severity: str
    rule_id: str
    title: str
    detail: str
    recommendation: str


class McpRiskAnalysisResponse(BaseModel):
    overall: str
    high_count: int
    medium_count: int
    low_count: int
    findings: list[McpRiskFinding]


@router.post("/analyze-risk", response_model=McpRiskAnalysisResponse)
async def analyze_mcp_risk_endpoint(
    body: McpRiskAnalyzeRequest,
    current_user: CurrentActiveUser,
):
    """Run the static risk advisor against an in-progress MCP config payload.

    Pure rule check - does NOT spawn anything, does NOT write to the DB. Used
    by the Add/Request modal for live feedback and by the Approvals review
    screen to show findings alongside a pending request.

    Available to anyone who can view the MCP page. Findings are advisory; no
    action is taken automatically.
    """
    await _require_mcp_permission(current_user, "view_mcp_page")
    payload = body.model_dump(exclude_none=True, mode="json")
    analysis = analyze_mcp_risk(payload, mode=body.mode)
    return McpRiskAnalysisResponse(**analysis.to_dict())


@router.post("/{server_id}/probe", response_model=McpProbeResponse)
async def probe_mcp_server(
    server_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Probe a registered MCP server: test connectivity and discover tools."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    row = await session.get(McpRegistry, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    if (row.approval_status or "approved") != "approved":
        raise HTTPException(status_code=400, detail="MCP server request is not approved yet")

    try:
        result = await probe_mcp_server_via_service(str(server_id))
        if isinstance(result, dict):
            if result.get("success"):
                row.tools_count = result.get("tools_count")
                if result.get("tools") is not None:
                    row.tools_snapshot = result.get("tools")
            row.tools_checked_at = datetime.now(timezone.utc)
            session.add(row)
            await session.commit()
        return McpProbeResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("MCP probe failed for server %s: %s", server_id, e)
        return McpProbeResponse(success=False, message=str(e))
