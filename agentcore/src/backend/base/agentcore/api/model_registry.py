"""REST endpoints for the model registry with approval-enforced promotion rules."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.model_service_client import (
    create_registry_model_via_service,
    delete_registry_model_via_service,
    fetch_registry_models_async,
    get_registry_model_via_service,
    test_connection_via_service,
    test_embedding_connection_via_service,
    update_registry_model_via_service,
)
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.model_approval_request.model import (
    ModelApprovalRequest,
    ModelApprovalRequestType,
)
from agentcore.services.database.models.model_audit_log.model import ModelAuditLog
from agentcore.services.database.models.model_registry.model import (
    ModelApprovalStatus,
    ModelEnvironment,
    ModelRegistry,
    ModelRegistryCreate,
    ModelRegistryRead,
    ModelRegistryUpdate,
    ModelVisibilityScope,
    TestConnectionRequest,
    TestConnectionResponse,
)
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.role.model import Role
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.approval_notifications import upsert_approval_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models/registry", tags=["Model Registry"])


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


def _normalize_environment(value: str | None) -> str:
    normalized = (value or ModelEnvironment.UAT.value).strip().lower()
    if normalized in {"dev", "test"}:
        normalized = ModelEnvironment.UAT.value
    if normalized not in {ModelEnvironment.UAT.value, ModelEnvironment.PROD.value}:
        raise HTTPException(status_code=400, detail=f"Unsupported environment '{value}'")
    return normalized


def _normalize_environment_list(values: list[str] | None, fallback: str | None = None) -> list[str]:
    normalized = [_normalize_environment(v) for v in (values or []) if v is not None]
    if not normalized and fallback is not None:
        normalized = [_normalize_environment(fallback)]
    ordered: list[str] = []
    for env in (ModelEnvironment.UAT.value, ModelEnvironment.PROD.value):
        if env in normalized and env not in ordered:
            ordered.append(env)
    for env in normalized:
        if env not in ordered:
            ordered.append(env)
    return ordered


def _resolve_model_environments(row: ModelRegistry) -> list[str]:
    envs = [str(v).lower() for v in (getattr(row, "environments", None) or []) if v]
    if envs:
        return _normalize_environment_list(envs)
    return [_normalize_environment(getattr(row, "environment", None))]


def _normalize_visibility_scope(value: str | None) -> str:
    normalized = (value or ModelVisibilityScope.PRIVATE.value).strip().lower()
    if normalized not in {
        ModelVisibilityScope.PRIVATE.value,
        ModelVisibilityScope.DEPARTMENT.value,
        ModelVisibilityScope.ORGANIZATION.value,
    }:
        raise HTTPException(status_code=400, detail=f"Unsupported visibility_scope '{value}'")
    return normalized


async def _validate_model_connection_before_create(body: ModelRegistryCreate) -> None:
    if not str(body.api_key or "").strip():
        raise HTTPException(status_code=400, detail="API key is required to create a model")

    payload = TestConnectionRequest(
        provider=body.provider,
        model_name=body.model_name,
        base_url=body.base_url,
        api_key=body.api_key,
        provider_config=body.provider_config,
    )
    if str(body.model_type or "").strip().lower() == "embedding":
        result = await test_embedding_connection_via_service(payload.model_dump())
    else:
        result = await test_connection_via_service(payload.model_dump(mode="json"))

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("message") or "Model connection test failed",
        )


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    normalized = _normalize_role_variants(getattr(current_user, "role", ""))
    return "root" in normalized


def _is_super_admin_user(current_user: CurrentActiveUser) -> bool:
    normalized = _normalize_role_variants(getattr(current_user, "role", ""))
    return bool(normalized.intersection({"super_admin", "superadmin"}))


def _normalize_role_variants(role: object) -> set[str]:
    raw = str(role or "").strip()
    if not raw:
        return set()
    lowered = raw.lower()
    normalized = {
        lowered,
        lowered.replace(" ", "_"),
        lowered.replace("-", "_"),
        lowered.replace(" ", "_").replace("-", "_"),
    }
    if "." in lowered:
        normalized.add(lowered.split(".")[-1].replace("-", "_"))
    normalized.add(normalize_role(raw))
    return normalized


def _can_self_approve(current_user: CurrentActiveUser) -> bool:
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


async def _require_any_permission(current_user: CurrentActiveUser, permissions: set[str]) -> None:
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
        await session.exec(
            select(Department.id).where(Department.org_id == org_id, Department.id.in_(dept_ids))
        )
    ).all()
    if len({str(r if isinstance(r, UUID) else r[0]) for r in rows}) != len({str(d) for d in dept_ids}):
        raise HTTPException(status_code=400, detail="One or more public_dept_ids are invalid for org_id")


async def _get_department_ids_for_org(session: DbSession, org_id: UUID) -> list[UUID]:
    rows = (await session.exec(select(Department.id).where(Department.org_id == org_id))).all()
    return [r if isinstance(r, UUID) else r[0] for r in rows]


async def _resolve_department_admin_approver(
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> UUID:
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


async def _append_audit(
    session: DbSession,
    *,
    model_id: UUID | None,
    actor_id: UUID | None,
    action: str,
    org_id: UUID | None = None,
    dept_id: UUID | None = None,
    from_environment: str | None = None,
    to_environment: str | None = None,
    from_visibility: str | None = None,
    to_visibility: str | None = None,
    details: dict | None = None,
    message: str | None = None,
) -> None:
    session.add(
        ModelAuditLog(
            model_id=model_id,
            actor_id=actor_id,
            action=action,
            org_id=org_id,
            dept_id=dept_id,
            from_environment=from_environment,
            to_environment=to_environment,
            from_visibility=from_visibility,
            to_visibility=to_visibility,
            details=details,
            message=message,
        )
    )


def _can_access_model(
    row: ModelRegistry,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return True
    if not row.org_id:
        return False

    role = normalize_role(str(current_user.role))
    user_id = str(current_user.id)

    if role == "super_admin" and row.org_id and row.org_id in org_ids:
        return True

    if (row.approval_status or ModelApprovalStatus.APPROVED.value) != ModelApprovalStatus.APPROVED.value:
        return str(row.requested_by or "") == user_id or str(row.request_to or "") == user_id

    visibility_scope = _normalize_visibility_scope(getattr(row, "visibility_scope", None))
    if visibility_scope == ModelVisibilityScope.PRIVATE.value:
        if role == "department_admin":
            dept_ids = {str(d) for _, d in dept_pairs}
            return bool(row.dept_id and str(row.dept_id) in dept_ids)
        return (
            str(row.created_by_id or "") == user_id
            or str(row.requested_by or "") == user_id
            or str(getattr(row, "created_by", "")) == str(getattr(current_user, "username", ""))
        )
    if visibility_scope == ModelVisibilityScope.DEPARTMENT.value:
        dept_ids = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if row.dept_id and str(row.dept_id) in dept_ids:
            return True
        return bool(scoped_public_depts.intersection(dept_ids))
    if visibility_scope == ModelVisibilityScope.ORGANIZATION.value:
        return bool(row.org_id and row.org_id in org_ids)
    return False


def _is_department_scoped_model(row: ModelRegistry, dept_pairs: list[tuple[UUID, UUID]]) -> bool:
    user_dept_ids = {str(dept_id) for _, dept_id in dept_pairs}
    model_dept_ids = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
    if row.dept_id:
        model_dept_ids.add(str(row.dept_id))
    return bool(model_dept_ids.intersection(user_dept_ids))


def _can_delete_model(
    row: ModelRegistry,
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

    # Developer/Business User: never delete.
    if normalized_roles.intersection({"developer", "business_user"}):
        return False

    # Department Admin: can delete only models approved by self.
    if normalized_roles.intersection({"department_admin"}):
        if len(list(getattr(row, "public_dept_ids", None) or [])) > 1:
            return False
        reviewed_by = str(getattr(row, "reviewed_by", "") or "")
        visibility_scope = _normalize_visibility_scope(getattr(row, "visibility_scope", None))
        dept_ids = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if visibility_scope == ModelVisibilityScope.DEPARTMENT.value:
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
            if scoped_public_depts.intersection(dept_ids):
                return True
        if visibility_scope == ModelVisibilityScope.PRIVATE.value:
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
        if reviewed_by == user_id:
            return True
        if not reviewed_by:
            return (
                str(getattr(row, "created_by_id", "") or "") == user_id
                and (row.approval_status or ModelApprovalStatus.APPROVED.value) == ModelApprovalStatus.APPROVED.value
            )
        return False

    # Super Admin: can delete any model within their org scope.
    if normalized_roles.intersection({"super_admin", "superadmin"}):
        return bool(row.org_id and row.org_id in org_ids)

    return False


def _can_edit_model(
    row: ModelRegistry,
    current_user: CurrentActiveUser,
    *,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user) or _is_super_admin_user(current_user):
        return True
    normalized_roles = _normalize_role_variants(getattr(current_user, "role", ""))
    user_id = str(current_user.id)
    visibility_scope = _normalize_visibility_scope(getattr(row, "visibility_scope", None))
    dept_ids = {str(d) for _, d in dept_pairs}
    scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}

    if normalized_roles.intersection({"department_admin"}):
        if len(list(getattr(row, "public_dept_ids", None) or [])) > 1:
            return False
        if visibility_scope == ModelVisibilityScope.ORGANIZATION.value:
            return False
        if visibility_scope == ModelVisibilityScope.DEPARTMENT.value:
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
            if scoped_public_depts.intersection(dept_ids):
                return True
        if visibility_scope == ModelVisibilityScope.PRIVATE.value:
            if row.dept_id and str(row.dept_id) in dept_ids:
                return True
        return (
            str(getattr(row, "reviewed_by", "") or "") == user_id
            or str(getattr(row, "created_by_id", "") or "") == user_id
        )

    return False

async def _create_model_approval_request(
    session: DbSession,
    *,
    model_id: UUID,
    org_id: UUID | None,
    dept_id: UUID | None,
    request_type: ModelApprovalRequestType,
    source_environment: str,
    target_environment: str,
    requested_environments: list[str] | None,
    visibility_requested: str,
    requested_by: UUID,
    request_to: UUID,
    public_dept_ids: list[UUID] | None = None,
) -> ModelApprovalRequest:
    req = ModelApprovalRequest(
        model_id=model_id,
        org_id=org_id,
        dept_id=dept_id,
        request_type=request_type,
        source_environment=source_environment,
        target_environment=target_environment,
        requested_environments=[str(v).lower() for v in (requested_environments or [])] or None,
        visibility_requested=visibility_requested,
        requested_by=requested_by,
        request_to=request_to,
        public_dept_ids=[str(d) for d in public_dept_ids] if public_dept_ids else None,
    )
    session.add(req)
    await session.flush()
    model_row = await session.get(ModelRegistry, model_id)
    model_label = getattr(model_row, "name", None) or getattr(model_row, "model_name", None) or "Model"
    await upsert_approval_notification(
        session,
        recipient_user_id=request_to,
        entity_type="model_request",
        entity_id=str(req.id),
        title=f'Model "{model_label}" awaiting your approval.',
        link="/approval",
    )
    return req


async def _has_pending_model_request(
    session: DbSession,
    *,
    model_id: UUID,
    request_type: ModelApprovalRequestType | None = None,
) -> bool:
    stmt = select(ModelApprovalRequest).where(
        ModelApprovalRequest.model_id == model_id,
        ModelApprovalRequest.decision == None,  # noqa: E711
    )
    if request_type is not None:
        stmt = stmt.where(ModelApprovalRequest.request_type == request_type)
    existing = (await session.exec(stmt.order_by(ModelApprovalRequest.requested_at.desc()))).first()
    return existing is not None


def _next_environment(current_envs: list[str]) -> str | None:
    normalized = _normalize_environment_list(current_envs)
    if ModelEnvironment.UAT.value in normalized and ModelEnvironment.PROD.value not in normalized:
        return ModelEnvironment.PROD.value
    return None


def _requires_super_admin_approval(*, target_environment: str, visibility_scope: str) -> bool:
    normalized_visibility = _normalize_visibility_scope(visibility_scope)
    return normalized_visibility == ModelVisibilityScope.ORGANIZATION.value


async def _resolve_approver_for_model_request(
    session: DbSession,
    current_user: CurrentActiveUser,
    *,
    target_environment: str,
    visibility_scope: str,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> UUID:
    if _requires_super_admin_approval(
        target_environment=target_environment,
        visibility_scope=visibility_scope,
    ):
        return await _resolve_super_admin_approver(session, current_user, org_id)
    return await _resolve_department_admin_approver(session, current_user, org_id, dept_id)


class PromoteModelPayload(ModelRegistryUpdate):
    target_environment: str


class ModelVisibilityChangePayload(ModelRegistryUpdate):
    visibility_scope: str
    org_id: UUID | None = None
    dept_id: UUID | None = None
    public_dept_ids: list[UUID] | None = None


@router.get("/visibility-options")
async def get_model_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models"})
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


@router.get("/", response_model=list[ModelRegistryRead])
async def list_registry_models(
    session: DbSession,
    current_user: CurrentActiveUser,
    provider: str | None = None,
    environment: str | None = None,
    model_type: str | None = None,
    active_only: bool = True,
):
    """List visible models only (tenant + visibility aware)."""
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models"})
    normalized_env = _normalize_environment(environment) if environment else None
    raw_rows = await fetch_registry_models_async(
        provider=provider,
        environment=normalized_env,
        model_type=model_type,
        active_only=active_only,
    )
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    model_ids: list[UUID] = []
    for row in raw_rows:
        try:
            model_ids.append(UUID(str(row.get("id"))))
        except Exception:
            continue
    if not model_ids:
        return []
    db_rows = (await session.exec(select(ModelRegistry).where(ModelRegistry.id.in_(model_ids)))).all()
    db_by_id = {row.id: row for row in db_rows}
    creator_ids = [row.created_by_id for row in db_rows if row.created_by_id]
    creator_identities = {
        str(row.created_by).strip().lower()
        for row in db_rows
        if row.created_by and str(row.created_by).strip()
    }
    creator_lookup: dict[str, dict[str, str | None]] = {}
    if creator_ids:
        creator_rows = (
            await session.exec(
                select(User.id, User.display_name, User.email, User.username).where(User.id.in_(creator_ids))
            )
        ).all()
        creator_lookup = {
            str(row[0]): {
                "display": _creator_display_name(row[1], row[2]),
                "email": _creator_email(row[2], row[3]),
            }
            for row in creator_rows
        }
    creator_identity_lookup: dict[str, dict[str, str | None]] = {}
    if creator_identities:
        creator_identity_rows = (
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
            for row in creator_identity_rows
            if str(row[1] or row[2]).strip()
        }
    pending_reqs = (
        await session.exec(
            select(ModelApprovalRequest)
            .where(
                ModelApprovalRequest.model_id.in_(model_ids),
                ModelApprovalRequest.decision == None,  # noqa: E711
            )
            .order_by(ModelApprovalRequest.requested_at.desc())
        )
    ).all()
    pending_by_model: dict[UUID, ModelApprovalRequest] = {}
    for req in pending_reqs:
        if req.model_id not in pending_by_model:
            pending_by_model[req.model_id] = req

    visible: list[ModelRegistryRead] = []
    for raw in raw_rows:
        try:
            model_id = UUID(str(raw.get("id")))
        except Exception:
            continue
        row = db_by_id.get(model_id)
        if not row:
            continue
        if not _can_access_model(row, current_user, org_ids, dept_pairs):
            continue
        envs = _resolve_model_environments(row)
        if not envs:
            pending_req = pending_by_model.get(model_id)
            if pending_req:
                requested_envs = [str(v).lower() for v in (getattr(pending_req, "requested_environments", None) or []) if v]
                if requested_envs:
                    envs = _normalize_environment_list(requested_envs)
                elif pending_req.target_environment:
                    envs = _normalize_environment_list([pending_req.target_environment])
        if normalized_env:
            if normalized_env not in envs:
                continue
        obj = ModelRegistryRead.from_orm_model(row)
        creator_meta = creator_lookup.get(str(row.created_by_id)) if row.created_by_id else None
        if not creator_meta and row.created_by:
            creator_meta = creator_identity_lookup.get(str(row.created_by).strip().lower())
        if creator_meta:
            obj.created_by = creator_meta.get("display") or row.created_by
            obj.created_by_email = creator_meta.get("email")
        if envs:
            obj.environments = envs
            obj.environment = envs[0]
        visible.append(obj)
    visible.sort(key=lambda item: (str(item.display_name or item.model_name or "")).strip().lower())
    return visible


@router.post("/", response_model=ModelRegistryRead, status_code=201)
async def create_registry_model(
    body: ModelRegistryCreate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Create model through approval-safe flow."""
    await _require_any_permission(current_user, {"add_new_model", "request_new_model"})
    desired_environment = _normalize_environment(body.environment)
    normalized_envs = _normalize_environment_list(getattr(body, "environments", None), desired_environment)
    normalized_final_env: str | None = None
    visibility_scope = _normalize_visibility_scope(getattr(body, "visibility_scope", None))
    requested_public_dept_ids = list(getattr(body, "public_dept_ids", None) or [])
    now = datetime.now(timezone.utc)

    if not body.created_by and current_user:
        body.created_by = current_user.username
    body.created_by_id = current_user.id
    body.visibility_scope = visibility_scope

    user_role = normalize_role(str(current_user.role))
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)

    if body.org_id and user_role != "root" and body.org_id not in org_ids:
        raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
    if body.dept_id:
        dept_set = {dept for _, dept in dept_pairs}
        if user_role not in {"root", "super_admin"} and body.dept_id not in dept_set:
            raise HTTPException(status_code=403, detail="dept_id must belong to your department scope")

    if visibility_scope == ModelVisibilityScope.DEPARTMENT.value:
        if user_role in {"root", "super_admin"}:
            if not body.org_id:
                if not org_ids:
                    raise HTTPException(status_code=403, detail="No active organization scope found for requester")
                body.org_id = sorted(org_ids, key=lambda x: str(x))[0]
            if not requested_public_dept_ids and body.dept_id:
                requested_public_dept_ids = [body.dept_id]
            if not requested_public_dept_ids:
                requested_public_dept_ids = await _get_department_ids_for_org(session, body.org_id)
            if not requested_public_dept_ids:
                raise HTTPException(status_code=400, detail="No departments found for selected org_id")
            if requested_public_dept_ids:
                requested_public_dept_ids = list(dict.fromkeys(requested_public_dept_ids))
                if not body.org_id:
                    first_dept = (
                        await session.exec(select(Department).where(Department.id == requested_public_dept_ids[0]))
                    ).first()
                    if not first_dept:
                        raise HTTPException(status_code=400, detail="Invalid department selected")
                    body.org_id = first_dept.org_id
                await _validate_departments_exist_for_org(session, body.org_id, requested_public_dept_ids)
                body.dept_id = requested_public_dept_ids[0]
                body.public_dept_ids = requested_public_dept_ids
        else:
            if not dept_pairs:
                raise HTTPException(status_code=403, detail="No active department scope found for requester")
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            body.org_id = current_org_id
            body.dept_id = current_dept_id
            body.public_dept_ids = [current_dept_id]
    else:
        body.public_dept_ids = None

    if not body.org_id and dept_pairs:
        body.org_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0][0]
    if not body.dept_id and dept_pairs:
        body.dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0][1]
    if not body.org_id and org_ids:
        body.org_id = sorted(org_ids, key=lambda x: str(x))[0]
    if not body.org_id:
        raise HTTPException(status_code=400, detail="org_id is required to create a model")

    await _validate_scope_refs(session, body.org_id, body.dept_id)

    body.environment = normalized_envs[0] if normalized_envs else desired_environment
    body.environments = normalized_envs or [desired_environment]
    body.requested_by = current_user.id
    body.requested_at = now

    await _validate_model_connection_before_create(body)

    is_super_admin_creator = user_role in {"root", "super_admin"}
    is_department_admin_creator = user_role == "department_admin"
    auto_approve = is_super_admin_creator or (
        is_department_admin_creator and visibility_scope != ModelVisibilityScope.ORGANIZATION.value
    )
    if auto_approve:
        body.approval_status = ModelApprovalStatus.APPROVED.value
        body.reviewed_by = current_user.id
        body.reviewed_at = now
        body.is_active = True
    else:
        body.approval_status = ModelApprovalStatus.PENDING.value
        body.is_active = False
        body.request_to = None

    created_dict = await create_registry_model_via_service(body.model_dump(mode="json"))
    created_id = UUID(created_dict["id"])
    created_row = await session.get(ModelRegistry, created_id)
    if created_row is None:
        raise HTTPException(status_code=500, detail="Created model not found")
    if normalized_envs:
        current_envs = [str(v).lower() for v in (getattr(created_row, "environments", None) or []) if v]
        desired_envs = _normalize_environment_list(normalized_envs)
        if current_envs != desired_envs:
            created_row.environments = desired_envs
            created_row.environment = desired_envs[0]
            session.add(created_row)

    await _append_audit(
        session,
        model_id=created_id,
        actor_id=current_user.id,
        action="model.create",
        org_id=created_row.org_id,
        dept_id=created_row.dept_id,
        to_environment=desired_environment,
        to_visibility=visibility_scope,
        details={"requested_environment": desired_environment},
        message="Model created",
    )

    if not auto_approve:
        # Approver policy:
        # - ORGANIZATION visibility (any env): super admin
        # - otherwise: department admin
        request_to = await _resolve_approver_for_model_request(
            session,
            current_user,
            target_environment=desired_environment,
            visibility_scope=visibility_scope,
            org_id=created_row.org_id,
            dept_id=created_row.dept_id,
        )

        if request_to == current_user.id and _can_self_approve(current_user):
            created_row.approval_status = ModelApprovalStatus.APPROVED.value
            created_row.reviewed_by = current_user.id
            created_row.reviewed_at = now
            created_row.is_active = True
            created_row.request_to = None
            session.add(created_row)
            await _append_audit(
                session,
                model_id=created_id,
                actor_id=current_user.id,
                action="model.create.auto_approved",
                org_id=created_row.org_id,
                dept_id=created_row.dept_id,
                from_environment=desired_environment,
                to_environment=desired_environment,
                from_visibility=visibility_scope,
                to_visibility=visibility_scope,
                details={"auto_approved": True, "reason": "requester_is_admin_approver"},
                message="Model request auto-approved by admin requester",
            )
        else:
            if request_to == current_user.id:
                raise HTTPException(status_code=400, detail="No user can approve their own request")

            await _create_model_approval_request(
                session,
                model_id=created_id,
                org_id=created_row.org_id,
                dept_id=created_row.dept_id,
                request_type=ModelApprovalRequestType.CREATE,
                source_environment=desired_environment,
                target_environment=desired_environment,
                requested_environments=normalized_envs,
                visibility_requested=visibility_scope,
                requested_by=current_user.id,
                request_to=request_to,
            )

            created_row.request_to = request_to
            session.add(created_row)

            await _append_audit(
                session,
                model_id=created_id,
                actor_id=current_user.id,
                action="model.create.requested",
                org_id=created_row.org_id,
                dept_id=created_row.dept_id,
                from_environment=desired_environment,
                to_environment=desired_environment,
                from_visibility=visibility_scope,
                to_visibility=visibility_scope,
                details={"requested_environment": desired_environment, "requested_visibility": visibility_scope},
                message="Model onboarding approval request created",
            )

    await session.commit()
    await session.refresh(created_row)

    # Semantic search: upsert embedding (fire-and-forget)
    asyncio.create_task(_upsert_model_embedding(created_row))

    return ModelRegistryRead.from_orm_model(created_row)


async def _upsert_model_embedding(model) -> None:
    try:
        from agentcore.services.semantic_search import upsert_entity_embedding

        tags = [model.provider, model.model_name] if model.provider else []
        await upsert_entity_embedding(
            entity_type="models",
            entity_id=str(model.id),
            name=model.display_name,
            description=model.description,
            tags=tags,
            org_id=str(model.org_id) if getattr(model, "org_id", None) else None,
            dept_id=str(model.dept_id) if getattr(model, "dept_id", None) else None,
            user_id=str(model.created_by_id) if getattr(model, "created_by_id", None) else None,
        )
    except Exception:
        logger.warning("[SEMANTIC] Failed to upsert model embedding for %s", model.id)


@router.post("/{model_id}/promote", response_model=ModelRegistryRead)
async def request_model_promotion(
    model_id: UUID,
    body: PromoteModelPayload,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"request_new_model", "add_new_model", "edit_model"})
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_edit_model(row, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="Model is outside your edit scope")

    target_environment = _normalize_environment(body.target_environment)
    current_envs = _resolve_model_environments(row)
    allowed_next = _next_environment(current_envs)
    if not allowed_next or target_environment != allowed_next:
        raise HTTPException(status_code=400, detail="Invalid promotion path. Use UAT->PROD only")
    if await _has_pending_model_request(session, model_id=row.id, request_type=ModelApprovalRequestType.PROMOTE):
        raise HTTPException(status_code=400, detail="A promotion request is already pending for this model")

    current_role = normalize_role(str(current_user.role))
    if current_role == "department_admin":
        if len(list(getattr(row, "public_dept_ids", None) or [])) > 1:
            raise HTTPException(
                status_code=403,
                detail="Promotion for multi-department models requires super admin",
            )

    if _is_root_user(current_user) or _is_super_admin_user(current_user):
        approver_id = current_user.id
    else:
        approver_id = await _resolve_approver_for_model_request(
            session,
            current_user,
            target_environment=target_environment,
            visibility_scope=row.visibility_scope,
            org_id=row.org_id,
            dept_id=row.dept_id,
        )
    if _is_root_user(current_user) or _is_super_admin_user(current_user) or (
        approver_id == current_user.id and _can_self_approve(current_user)
    ):
        now = datetime.now(timezone.utc)
        row.environments = _normalize_environment_list([*current_envs, target_environment])
        row.environment = row.environments[0] if row.environments else target_environment
        row.approval_status = ModelApprovalStatus.APPROVED.value
        row.requested_by = current_user.id
        row.request_to = None
        row.requested_at = None
        row.reviewed_by = current_user.id
        row.reviewed_at = now
        row.is_active = True
        session.add(row)
        await _append_audit(
            session,
            model_id=row.id,
            actor_id=current_user.id,
            action="model.promotion.auto_approved",
            org_id=row.org_id,
            dept_id=row.dept_id,
            from_environment=",".join(current_envs),
            to_environment=",".join(row.environments or []),
            details={"auto_approved": True, "reason": "requester_is_admin_approver"},
            message="Promotion auto-approved by admin requester",
        )
        await session.commit()
        await session.refresh(row)
        return ModelRegistryRead.from_orm_model(row)
    if approver_id == current_user.id:
        raise HTTPException(status_code=400, detail="No user can approve their own request")

    now = datetime.now(timezone.utc)
    row.approval_status = ModelApprovalStatus.PENDING.value
    row.requested_by = current_user.id
    row.request_to = approver_id
    row.requested_at = now
    row.is_active = False
    session.add(row)

    await _create_model_approval_request(
        session,
        model_id=row.id,
        org_id=row.org_id,
        dept_id=row.dept_id,
        request_type=ModelApprovalRequestType.PROMOTE,
        source_environment=current_envs[0] if current_envs else ModelEnvironment.UAT.value,
        target_environment=target_environment,
        requested_environments=[*current_envs, target_environment] if current_envs else [target_environment],
        visibility_requested=row.visibility_scope,
        requested_by=current_user.id,
        request_to=approver_id,
    )
    await _append_audit(
        session,
        model_id=row.id,
        actor_id=current_user.id,
        action="model.promotion.requested",
        org_id=row.org_id,
        dept_id=row.dept_id,
        from_environment=",".join(current_envs),
        to_environment=target_environment,
        message="Promotion request created",
    )
    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


@router.post("/{model_id}/visibility", response_model=ModelRegistryRead)
async def request_model_visibility_change(
    model_id: UUID,
    body: ModelVisibilityChangePayload,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"request_new_model", "add_new_model", "edit_model"})
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_edit_model(row, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="Model is outside your edit scope")
    if await _has_pending_model_request(session, model_id=row.id, request_type=ModelApprovalRequestType.VISIBILITY):
        raise HTTPException(status_code=400, detail="A visibility change request is already pending for this model")
    target_visibility = _normalize_visibility_scope(body.visibility_scope)

    requested_public_dept_ids = list(getattr(body, "public_dept_ids", None) or [])
    requested_dept_id = getattr(body, "dept_id", None)
    requested_org_id = getattr(body, "org_id", None) or row.org_id
    current_role = normalize_role(str(current_user.role))
    dept_ids = {str(d) for _, d in dept_pairs}
    if current_role == "department_admin":
        if len(list(getattr(row, "public_dept_ids", None) or [])) > 1:
            raise HTTPException(
                status_code=403,
                detail="Multi-department visibility changes require super admin",
            )
        if target_visibility == ModelVisibilityScope.DEPARTMENT.value and len(requested_public_dept_ids) > 1:
            raise HTTPException(
                status_code=403,
                detail="Multi-department visibility changes require super admin",
            )
        if target_visibility == ModelVisibilityScope.DEPARTMENT.value and requested_public_dept_ids:
            if any(str(d) not in dept_ids for d in requested_public_dept_ids):
                raise HTTPException(
                    status_code=403,
                    detail="Department admins can only target their own department",
                )
        if target_visibility == ModelVisibilityScope.PRIVATE.value and requested_dept_id:
            if str(requested_dept_id) not in dept_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Department admins can only target their own department",
                )
    if target_visibility == row.visibility_scope:
        current_public = [str(v) for v in (row.public_dept_ids or [])]
        desired_public = [str(v) for v in (requested_public_dept_ids or [])]
        current_public.sort()
        desired_public.sort()
        scope_changed = False
        if target_visibility == ModelVisibilityScope.DEPARTMENT.value:
            scope_changed = (
                (row.org_id != requested_org_id)
                or (str(row.dept_id) if row.dept_id else None) != (str(requested_dept_id) if requested_dept_id else None)
                or current_public != desired_public
            )
        elif target_visibility == ModelVisibilityScope.PRIVATE.value:
            scope_changed = (
                (row.org_id != requested_org_id)
                or (str(row.dept_id) if row.dept_id else None) != (str(requested_dept_id) if requested_dept_id else None)
            )
        elif target_visibility == ModelVisibilityScope.ORGANIZATION.value:
            scope_changed = row.org_id != requested_org_id
        if not scope_changed:
            raise HTTPException(status_code=400, detail="No visibility changes detected")

    if target_visibility == ModelVisibilityScope.DEPARTMENT.value:
        if requested_public_dept_ids:
            requested_public_dept_ids = list(dict.fromkeys(requested_public_dept_ids))
        if not requested_public_dept_ids and requested_dept_id:
            requested_public_dept_ids = [requested_dept_id]
        if not requested_public_dept_ids:
            raise HTTPException(status_code=400, detail="Department selection is required for department visibility")
        if not requested_org_id:
            raise HTTPException(status_code=400, detail="org_id is required for department visibility change")
        await _validate_departments_exist_for_org(session, requested_org_id, requested_public_dept_ids)
        requested_dept_id = requested_public_dept_ids[0]
    else:
        requested_public_dept_ids = []
        if target_visibility == ModelVisibilityScope.PRIVATE.value:
            requested_org_id = requested_org_id or row.org_id
            if not requested_dept_id:
                if current_role in {"department_admin", "developer", "business_user"} and dept_pairs:
                    current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
                    requested_org_id = requested_org_id or current_org_id
                    requested_dept_id = current_dept_id
                else:
                    owner_id = row.created_by_id or row.requested_by
                    owner_org_id, owner_dept_id = await _resolve_user_primary_dept(session, owner_id)
                    if owner_org_id and not requested_org_id:
                        requested_org_id = owner_org_id
                    if owner_dept_id:
                        requested_dept_id = owner_dept_id
            requested_dept_id = requested_dept_id or row.dept_id
            if not requested_dept_id and not (_is_root_user(current_user) or _is_super_admin_user(current_user)):
                raise HTTPException(status_code=400, detail="dept_id is required for private visibility")
        else:
            requested_dept_id = None
    if current_role == "department_admin":
        if target_visibility == ModelVisibilityScope.DEPARTMENT.value:
            if any(str(d) not in dept_ids for d in requested_public_dept_ids):
                raise HTTPException(
                    status_code=403,
                    detail="Department admins can only target their own department",
                )
        if target_visibility == ModelVisibilityScope.PRIVATE.value and requested_dept_id:
            if str(requested_dept_id) not in dept_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Department admins can only target their own department",
                )

    if _is_root_user(current_user) or _is_super_admin_user(current_user):
        approver_id = current_user.id
    else:
        approver_id = await _resolve_approver_for_model_request(
            session,
            current_user,
            target_environment=row.environment,
            visibility_scope=target_visibility,
            org_id=requested_org_id,
            dept_id=requested_dept_id,
        )
    if _is_root_user(current_user) or _is_super_admin_user(current_user) or (
        approver_id == current_user.id and _can_self_approve(current_user)
    ):
        now = datetime.now(timezone.utc)
        row.visibility_scope = target_visibility
        if target_visibility == ModelVisibilityScope.DEPARTMENT.value:
            row.org_id = requested_org_id
            row.dept_id = requested_dept_id
            row.public_dept_ids = [str(d) for d in (requested_public_dept_ids or [])] or None
        elif target_visibility == ModelVisibilityScope.ORGANIZATION.value:
            row.org_id = requested_org_id
            row.dept_id = None
            row.public_dept_ids = None
        else:
            row.org_id = requested_org_id
            if requested_dept_id:
                row.dept_id = requested_dept_id
            row.public_dept_ids = None
        if target_visibility == ModelVisibilityScope.PRIVATE.value:
            row.created_by_id = current_user.id
            row.created_by = getattr(current_user, "username", row.created_by)
        row.approval_status = ModelApprovalStatus.APPROVED.value
        row.requested_by = current_user.id
        row.request_to = None
        row.requested_at = None
        row.reviewed_by = current_user.id
        row.reviewed_at = now
        row.is_active = True
        session.add(row)
        await _append_audit(
            session,
            model_id=row.id,
            actor_id=current_user.id,
            action="model.visibility.auto_approved",
            org_id=row.org_id,
            dept_id=row.dept_id,
            from_visibility=row.visibility_scope,
            to_visibility=target_visibility,
            details={"auto_approved": True, "reason": "requester_is_admin_approver"},
            message="Visibility change auto-approved by admin requester",
        )
        await session.commit()
        await session.refresh(row)
        return ModelRegistryRead.from_orm_model(row)
    if approver_id == current_user.id:
        raise HTTPException(status_code=400, detail="No user can approve their own request")

    now = datetime.now(timezone.utc)
    row.approval_status = ModelApprovalStatus.PENDING.value
    row.requested_by = current_user.id
    row.request_to = approver_id
    row.requested_at = now
    session.add(row)

    await _create_model_approval_request(
        session,
        model_id=row.id,
        org_id=requested_org_id,
        dept_id=requested_dept_id,
        request_type=ModelApprovalRequestType.VISIBILITY,
        source_environment=_normalize_environment(row.environment),
        target_environment=_normalize_environment(row.environment),
        requested_environments=_resolve_model_environments(row),
        visibility_requested=target_visibility,
        requested_by=current_user.id,
        request_to=approver_id,
        public_dept_ids=requested_public_dept_ids or None,
    )
    await _append_audit(
        session,
        model_id=row.id,
        actor_id=current_user.id,
        action="model.visibility.requested",
        org_id=row.org_id,
        dept_id=row.dept_id,
        from_visibility=row.visibility_scope,
        to_visibility=target_visibility,
        message="Visibility change request created",
    )
    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


@router.get("/{model_id}", response_model=ModelRegistryRead)
async def get_registry_model(
    model_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models"})
    model_dict = await get_registry_model_via_service(str(model_id))
    if model_dict is None:
        raise HTTPException(status_code=404, detail="Model not found")
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_model(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Model is outside your visibility scope")
    return model_dict


@router.put("/{model_id}", response_model=ModelRegistryRead)
async def update_registry_model(
    model_id: UUID,
    body: ModelRegistryUpdate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"edit_model"})
    existing = await session.get(ModelRegistry, model_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Model not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_model(existing, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Model is outside your visibility scope")
    if not _can_edit_model(existing, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="Model is outside your edit scope")

    if body.environment and _normalize_environment(body.environment) != _normalize_environment(existing.environment):
        raise HTTPException(status_code=400, detail="Direct environment change is blocked. Use /promote flow")
    if body.environments is not None:
        desired_envs = _normalize_environment_list(body.environments)
        current_envs = _resolve_model_environments(existing)
        if desired_envs != current_envs:
            raise HTTPException(status_code=400, detail="Direct environment change is blocked. Use /promote flow")

    if body.visibility_scope and _normalize_visibility_scope(body.visibility_scope) != _normalize_visibility_scope(existing.visibility_scope):
        raise HTTPException(status_code=400, detail="Direct visibility change is blocked. Use /visibility flow")
    if body.org_id and body.org_id != existing.org_id:
        raise HTTPException(status_code=400, detail="org_id cannot be changed")

    model_dict = await update_registry_model_via_service(str(model_id), body.model_dump(mode="json", exclude_unset=True))
    if model_dict is None:
        raise HTTPException(status_code=404, detail="Model not found")

    await _append_audit(
        session,
        model_id=model_id,
        actor_id=current_user.id,
        action="model.updated",
        org_id=existing.org_id,
        dept_id=existing.dept_id,
        message="Model metadata updated",
    )
    await session.commit()

    # Semantic search: update embedding (fire-and-forget)
    refreshed = await session.get(ModelRegistry, model_id)
    if refreshed:
        asyncio.create_task(_upsert_model_embedding(refreshed))

    return model_dict


@router.delete("/{model_id}", status_code=204)
async def delete_registry_model(
    model_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"delete_model"})

    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_delete_model(row, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="You are not allowed to delete this model")

    approval_rows = (
        await session.exec(select(ModelApprovalRequest).where(ModelApprovalRequest.model_id == model_id))
    ).all()
    for req in approval_rows:
        await session.delete(req)

    audit_rows = (
        await session.exec(select(ModelAuditLog).where(ModelAuditLog.model_id == model_id))
    ).all()
    for audit in audit_rows:
        audit.model_id = None
        session.add(audit)

    await _append_audit(
        session,
        model_id=None,
        actor_id=current_user.id,
        action="model.deleted",
        org_id=row.org_id,
        dept_id=row.dept_id,
        details={"deleted_model_id": str(model_id)},
        message="Model deleted",
    )
    await session.commit()
    await delete_registry_model_via_service(str(model_id))

    # Semantic search: delete embedding (fire-and-forget)
    from agentcore.services.semantic_search import delete_entity_embedding

    asyncio.create_task(delete_entity_embedding("models", str(model_id)))


@router.get("/{model_id}/audit", response_model=list[dict])
async def get_model_audit_trail(
    model_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> list[dict]:
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models", "view_model"})
    rows = (
        await session.exec(
            select(ModelAuditLog).where(ModelAuditLog.model_id == model_id).order_by(ModelAuditLog.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "model_id": str(r.model_id) if r.model_id else None,
            "action": r.action,
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "org_id": str(r.org_id) if r.org_id else None,
            "dept_id": str(r.dept_id) if r.dept_id else None,
            "from_environment": r.from_environment,
            "to_environment": r.to_environment,
            "from_visibility": r.from_visibility,
            "to_visibility": r.to_visibility,
            "details": r.details,
            "message": r.message,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_model_connection(
    body: TestConnectionRequest,
    current_user: CurrentActiveUser,
):
    try:
        result = await test_connection_via_service(body.model_dump(mode="json"))
        return TestConnectionResponse(**result)
    except Exception as e:
        logger.warning("Test connection via microservice failed: %s", e)
        return TestConnectionResponse(success=False, message=str(e))


@router.post("/test-embedding-connection", response_model=TestConnectionResponse)
async def test_embedding_connection(
    body: TestConnectionRequest,
    current_user: CurrentActiveUser,
):
    try:
        return await test_embedding_connection_via_service(body.model_dump())
    except Exception as e:
        logger.warning("Test embedding connection via microservice failed: %s", e)
        return TestConnectionResponse(success=False, message=str(e))
