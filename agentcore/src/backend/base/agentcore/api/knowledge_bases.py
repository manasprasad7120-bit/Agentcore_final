from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlmodel import select as sm_select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.file.model import File as UserFile
from agentcore.services.database.models.knowledge_base.model import KBVisibilityEnum, KnowledgeBase
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.deps import get_storage_service
from agentcore.services.storage.service import StorageService

router = APIRouter(tags=["Knowledge Bases"], prefix="/knowledge_bases")


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_admin_role(role: str | None) -> bool:
    return normalize_role(role or "") in {"super_admin", "department_admin", "root"}


def _is_root_user(role: str | None) -> bool:
    return normalize_role(role or "") == "root"


async def _get_scope_memberships(session: DbSession, user_id: UUID) -> tuple[set[UUID], set[UUID]]:
    org_rows = (
        await session.exec(
            sm_select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            sm_select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    dept_ids = {r if isinstance(r, UUID) else r[0] for r in dept_rows}
    return org_ids, dept_ids


def _knowledge_base_visibility_predicate(
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_ids: set[UUID],
):
    """DB-enforced visibility predicate aligned with connector tenancy."""
    role = normalize_role(getattr(current_user, "role", None) or "")
    if _is_root_user(role):
        return and_(
            KnowledgeBase.created_by == current_user.id,
            KnowledgeBase.org_id.is_(None),
            KnowledgeBase.dept_id.is_(None),
        )

    predicates: list = []

    if role == "super_admin" and org_ids:
        predicates.append(KnowledgeBase.org_id.in_(list(org_ids)))

    if dept_ids:
        dept_visibility_predicates = [KnowledgeBase.dept_id.in_(list(dept_ids))]
        dept_visibility_predicates.extend(
            [KnowledgeBase.public_dept_ids.contains([str(d)]) for d in dept_ids]
        )
        predicates.append(
            and_(
                KnowledgeBase.visibility == KBVisibilityEnum.DEPARTMENT,
                or_(*dept_visibility_predicates),
            )
        )
        predicates.append(
            and_(
                KnowledgeBase.visibility == KBVisibilityEnum.PRIVATE,
                KnowledgeBase.created_by == current_user.id,
                KnowledgeBase.dept_id.in_(list(dept_ids)),
            )
        )
        if role == "department_admin":
            predicates.append(
                and_(
                    KnowledgeBase.visibility == KBVisibilityEnum.PRIVATE,
                    KnowledgeBase.dept_id.in_(list(dept_ids)),
                )
            )

    if org_ids:
        predicates.append(
            and_(
                KnowledgeBase.visibility == KBVisibilityEnum.ORGANIZATION,
                KnowledgeBase.org_id.in_(list(org_ids)),
            )
        )

    if not predicates:
        return KnowledgeBase.id.is_(None)
    return or_(*predicates)


def _kb_dept_candidates(kb: KnowledgeBase) -> set[str]:
    candidates = {str(v) for v in (kb.public_dept_ids or [])}
    if kb.dept_id:
        candidates.add(str(kb.dept_id))
    return candidates


def _is_multi_dept_kb(kb: KnowledgeBase) -> bool:
    return kb.visibility == KBVisibilityEnum.DEPARTMENT and len(_kb_dept_candidates(kb)) > 1


def _can_view_kb_row(
    row,
    *,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_ids: set[UUID],
) -> bool:
    role = normalize_role(getattr(current_user, "role", None) or "")
    if _is_root_user(role):
        return (
            row.created_by == current_user.id
            and row.org_id is None
            and row.dept_id is None
        )

    if role == "super_admin" and row.org_id and row.org_id in org_ids:
        return True

    if row.visibility == KBVisibilityEnum.PRIVATE:
        if row.created_by == current_user.id:
            return True
        if role == "department_admin":
            dept_candidates = {str(v) for v in (row.public_dept_ids or [])}
            if row.dept_id:
                dept_candidates.add(str(row.dept_id))
            return bool(dept_candidates.intersection({str(d) for d in dept_ids}))
        return False
    if row.visibility == KBVisibilityEnum.DEPARTMENT:
        dept_candidates = {str(v) for v in (row.public_dept_ids or [])}
        if row.dept_id:
            dept_candidates.add(str(row.dept_id))
        return bool(dept_candidates.intersection({str(d) for d in dept_ids}))
    if row.visibility == KBVisibilityEnum.ORGANIZATION:
        return bool(row.org_id and row.org_id in org_ids)
    return False


async def _can_edit_knowledge_base(
    session: DbSession,
    current_user: CurrentActiveUser,
    kb: KnowledgeBase,
) -> bool:
    role = normalize_role(getattr(current_user, "role", None) or "")
    if _is_root_user(role):
        return (
            kb.created_by == current_user.id
            and kb.org_id is None
            and kb.dept_id is None
        )

    org_ids, dept_ids = await _get_scope_memberships(session, current_user.id)

    if role == "super_admin":
        if (
            kb.visibility == KBVisibilityEnum.PRIVATE
            and kb.org_id is None
            and kb.dept_id is None
        ):
            return kb.created_by == current_user.id
        return bool(kb.org_id and kb.org_id in org_ids)

    if role == "department_admin":
        if _is_multi_dept_kb(kb):
            return False
        if kb.visibility == KBVisibilityEnum.ORGANIZATION:
            return False
        kb_dept_ids = {UUID(v) for v in _kb_dept_candidates(kb)}
        if kb.visibility == KBVisibilityEnum.DEPARTMENT:
            return bool(kb_dept_ids.intersection(dept_ids))
        if kb.visibility == KBVisibilityEnum.PRIVATE:
            return bool(kb_dept_ids.intersection(dept_ids))
        return False

    if role in {"developer", "business_user"}:
        return kb.visibility == KBVisibilityEnum.PRIVATE and kb.created_by == current_user.id

    return False


async def _can_delete_knowledge_base(
    session: DbSession,
    current_user: CurrentActiveUser,
    kb: KnowledgeBase,
) -> bool:
    role = normalize_role(getattr(current_user, "role", None) or "")
    if _is_root_user(role):
        return (
            kb.created_by == current_user.id
            and kb.org_id is None
            and kb.dept_id is None
        )

    org_ids, dept_ids = await _get_scope_memberships(session, current_user.id)

    if role == "super_admin":
        if (
            kb.visibility == KBVisibilityEnum.PRIVATE
            and kb.org_id is None
            and kb.dept_id is None
        ):
            return kb.created_by == current_user.id
        return bool(kb.org_id and kb.org_id in org_ids)

    if role == "department_admin":
        if _is_multi_dept_kb(kb):
            return False
        if kb.visibility == KBVisibilityEnum.ORGANIZATION:
            return False
        kb_dept_ids = {UUID(v) for v in _kb_dept_candidates(kb)}
        if kb.visibility == KBVisibilityEnum.DEPARTMENT:
            return bool(kb_dept_ids.intersection(dept_ids))
        if kb.visibility == KBVisibilityEnum.PRIVATE:
            return bool(kb_dept_ids.intersection(dept_ids))
        return False

    if role in {"developer", "business_user"}:
        return kb.visibility == KBVisibilityEnum.PRIVATE and kb.created_by == current_user.id

    return False


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


async def _enforce_kb_scope_for_update(
    session: DbSession,
    current_user: CurrentActiveUser,
    kb: KnowledgeBase,
    visibility: KBVisibilityEnum,
    public_scope: str | None,
    org_id: UUID | None,
    dept_id: UUID | None,
    public_dept_ids: list[UUID] | None,
) -> tuple[KBVisibilityEnum, UUID | None, UUID | None, list[str] | None]:
    org_ids, _ = await _get_scope_memberships(session, current_user.id)
    dept_rows = (
        await session.exec(
            sm_select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    dept_pairs = [(row[0], row[1]) for row in dept_rows]
    role = normalize_role(getattr(current_user, "role", None) or "")

    target_visibility = visibility
    target_org_id = org_id if org_id is not None else kb.org_id
    target_dept_id = dept_id if dept_id is not None else kb.dept_id
    requested_public_dept_ids = [str(v) for v in (public_dept_ids or [])] or list(
        getattr(kb, "public_dept_ids", None) or []
    )

    if target_visibility == KBVisibilityEnum.PRIVATE:
        if role in {"department_admin", "developer", "business_user"}:
            if not dept_pairs:
                raise HTTPException(status_code=403, detail="No active department scope found")
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            await _validate_scope_refs(session, current_org_id, current_dept_id)
            return KBVisibilityEnum.PRIVATE, current_org_id, current_dept_id, None
        return KBVisibilityEnum.PRIVATE, None, None, None

    if target_visibility == KBVisibilityEnum.ORGANIZATION:
        if not target_org_id:
            if role == "root":
                raise HTTPException(status_code=400, detail="org_id is required for organization visibility")
            if not org_ids:
                raise HTTPException(status_code=403, detail="No active organization scope found")
            target_org_id = sorted(org_ids, key=str)[0]
        if role != "root" and target_org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
        target_dept_id = None
        await _validate_scope_refs(session, target_org_id, target_dept_id)
        return target_visibility, target_org_id, target_dept_id, None

    if target_visibility == KBVisibilityEnum.DEPARTMENT:
        if role in {"super_admin", "root"}:
            if not target_org_id:
                if role == "root":
                    raise HTTPException(status_code=400, detail="org_id is required for department visibility")
                if not org_ids:
                    raise HTTPException(status_code=403, detail="No active organization scope found")
                target_org_id = sorted(org_ids, key=str)[0]
            if role != "root" and target_org_id not in org_ids:
                raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
            if public_scope is None:
                public_scope = "department"
            if not requested_public_dept_ids and target_dept_id:
                requested_public_dept_ids = [str(target_dept_id)]
            if not requested_public_dept_ids:
                raise HTTPException(status_code=400, detail="Select at least one department")
            await _validate_departments_exist_for_org(
                session,
                target_org_id,
                [UUID(v) for v in requested_public_dept_ids],
            )
            target_dept_id = UUID(requested_public_dept_ids[0]) if len(requested_public_dept_ids) == 1 else None
            await _validate_scope_refs(session, target_org_id, target_dept_id)
            return target_visibility, target_org_id, target_dept_id, requested_public_dept_ids

        if not dept_pairs:
            raise HTTPException(status_code=403, detail="No active department scope found")
        allowed_pairs = {(org, dept) for org, dept in dept_pairs}
        current_org_id, current_dept_id = sorted(allowed_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
        await _validate_scope_refs(session, current_org_id, current_dept_id)
        return target_visibility, current_org_id, current_dept_id, [str(current_dept_id)]

    if target_visibility.value == "PUBLIC":
        if not public_scope:
            raise HTTPException(status_code=400, detail="public_scope is required when visibility is public")
        normalized_public_scope = public_scope.strip().lower()
        if normalized_public_scope == "organization":
            return await _enforce_kb_scope_for_update(
                session,
                current_user,
                kb,
                KBVisibilityEnum.ORGANIZATION,
                public_scope,
                target_org_id,
                target_dept_id,
            )
        if normalized_public_scope == "department":
            return await _enforce_kb_scope_for_update(
                session,
                current_user,
                kb,
                KBVisibilityEnum.DEPARTMENT,
                public_scope,
                target_org_id,
                target_dept_id,
            )
        raise HTTPException(status_code=400, detail="Unsupported public_scope")

    return target_visibility, target_org_id, target_dept_id, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", status_code=HTTPStatus.OK)
@router.get("/", status_code=HTTPStatus.OK)
async def list_knowledge_bases(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    viewer_org_ids, viewer_dept_ids = await _get_scope_memberships(session, current_user.id)
    visibility_predicate = _knowledge_base_visibility_predicate(
        current_user,
        viewer_org_ids,
        viewer_dept_ids,
    )
    stmt = (
        select(
            KnowledgeBase.id,
            KnowledgeBase.name,
            KnowledgeBase.visibility,
            KnowledgeBase.org_id,
            KnowledgeBase.dept_id,
            KnowledgeBase.public_dept_ids,
            KnowledgeBase.created_by,
            KnowledgeBase.updated_by,
            KnowledgeBase.updated_at.label("kb_updated_at"),
            func.max(UserFile.updated_at).label("last_file_updated_at"),
            func.coalesce(func.sum(UserFile.size), 0).label("size"),
            func.count(UserFile.id).label("file_count"),
        )
        .select_from(KnowledgeBase)
        .join(UserFile, UserFile.knowledge_base_id == KnowledgeBase.id, isouter=True)
        .where(visibility_predicate)
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.name,
            KnowledgeBase.visibility,
            KnowledgeBase.org_id,
            KnowledgeBase.dept_id,
            KnowledgeBase.public_dept_ids,
            KnowledgeBase.created_by,
            KnowledgeBase.updated_by,
            KnowledgeBase.updated_at,
        )
        .order_by(KnowledgeBase.name.asc())
    )
    rows = (await session.exec(stmt)).all()

    payload: list[dict] = []
    role = normalize_role(getattr(current_user, "role", None) or "")
    # Build a single user-id -> {display, email} map covering both the
    # creator and the most-recent modifier. One DB roundtrip for both.
    user_lookup_ids: set[UUID] = set()
    for row in rows:
        if row.created_by:
            user_lookup_ids.add(row.created_by)
        if row.updated_by:
            user_lookup_ids.add(row.updated_by)
    creator_display_map: dict[UUID, str] = {}
    creator_email_map: dict[UUID, str] = {}
    dept_name_map: dict[UUID, str] = {}
    org_name_map: dict[UUID, str] = {}

    if user_lookup_ids:
        creator_rows = (
            await session.exec(
                select(User.id, User.display_name, User.email, User.username).where(User.id.in_(list(user_lookup_ids)))
            )
        ).all()
        creator_display_map = {
            uid: (
                (str(display_name or "").strip())
                or (
                    str(email).split("@", 1)[0]
                    if email and str(email).strip()
                    else (
                        str(username).split("@", 1)[0]
                        if username and str(username).strip()
                        else str(uid)
                    )
                )
            )
            for uid, display_name, email, username in creator_rows
        }
        creator_email_map = {
            uid: (
                str(email).strip()
                if email and str(email).strip()
                else (str(username).strip() if username and "@" in str(username) else "")
            )
            for uid, _display_name, email, username in creator_rows
        }

        if role in {"super_admin", "root"}:
            dept_ids = {row.dept_id for row in rows if row.dept_id}
            if dept_ids:
                dept_rows = (
                    await session.exec(
                        select(Department.id, Department.name).where(Department.id.in_(list(dept_ids)))
                    )
                ).all()
                dept_name_map = {dept_id: name for dept_id, name in dept_rows}

        if role == "root":
            org_ids = {row.org_id for row in rows if row.org_id}
            if org_ids:
                org_rows = (
                    await session.exec(
                        select(Organization.id, Organization.name).where(Organization.id.in_(list(org_ids)))
                    )
                ).all()
                org_name_map = {org_id: name for org_id, name in org_rows}

    for row in rows:
        timestamps = [_to_utc(ts) for ts in (row.kb_updated_at, row.last_file_updated_at)]
        timestamps = [ts for ts in timestamps if ts is not None]
        last_activity = max(timestamps) if timestamps else None
        is_own = row.created_by == current_user.id
        created_by_display = creator_display_map.get(row.created_by, str(row.created_by))
        created_by_email = creator_email_map.get(row.created_by)
        updated_by_display = (
            creator_display_map.get(row.updated_by) if row.updated_by else None
        )
        updated_by_email = (
            creator_email_map.get(row.updated_by) if row.updated_by else None
        )
        department_name = dept_name_map.get(row.dept_id) if row.dept_id else None
        organization_name = org_name_map.get(row.org_id) if row.org_id else None

        # created_by_email / updated_by_email are returned for every role so
        # the UI can show the email on hover. Department / organization
        # scope names remain gated by role below.
        if role in {"developer", "business_user"}:
            department_name = None
            organization_name = None
        elif role == "department_admin":
            department_name = None
            organization_name = None
        elif role == "super_admin":
            organization_name = None
        elif role == "root":
            department_name = None
            organization_name = None

        if not _can_view_kb_row(row, current_user=current_user, org_ids=viewer_org_ids, dept_ids=viewer_dept_ids):
            continue

        payload.append(
            {
                "id": str(row.id),
                "name": row.name,
                "visibility": row.visibility.value if row.visibility else "PRIVATE",
                "org_id": str(row.org_id) if row.org_id else None,
                "dept_id": str(row.dept_id) if row.dept_id else None,
                "public_dept_ids": [str(v) for v in (row.public_dept_ids or [])],
                "created_by": created_by_display,
                "size": int(row.size or 0),
                "words": 0,
                "characters": 0,
                "chunks": 0,
                "avg_chunk_size": 0,
                "file_count": int(row.file_count or 0),
                "updated_at": row.kb_updated_at.isoformat() if row.kb_updated_at else None,
                "last_activity": last_activity.isoformat() if last_activity else None,
                "is_own_kb": is_own,
                "created_by_email": created_by_email,
                "department_name": department_name,
                "organization_name": organization_name,
                "updated_by": updated_by_display,
                "updated_by_email": updated_by_email,
            }
        )

    payload.sort(
        key=lambda item: (
            str(item.get("last_activity") or item.get("updated_at") or "")
        ),
        reverse=True,
    )
    return payload


@router.get("/visibility-options", status_code=HTTPStatus.OK)
async def get_knowledge_base_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    org_ids, dept_ids = await _get_scope_memberships(session, current_user.id)
    role = normalize_role(getattr(current_user, "role", None) or "")

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


class KnowledgeBaseUpdate(BaseModel):
    visibility: KBVisibilityEnum
    public_scope: str | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    public_dept_ids: list[UUID] | None = None


@router.patch("/{kb_id}", status_code=HTTPStatus.OK)
async def update_knowledge_base(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    current_user: CurrentActiveUser,
    session: DbSession,
):
    """Update KB visibility. Only the creator or admins can change visibility."""
    kb = (
        await session.exec(
            sm_select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
    ).first()

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if not await _can_edit_knowledge_base(session, current_user, kb):
        raise HTTPException(status_code=403, detail="Not authorized to update this knowledge base")

    visibility, org_id, dept_id, public_dept_ids = await _enforce_kb_scope_for_update(
        session=session,
        current_user=current_user,
        kb=kb,
        visibility=payload.visibility,
        public_scope=payload.public_scope,
        org_id=payload.org_id,
        dept_id=payload.dept_id,
        public_dept_ids=payload.public_dept_ids,
    )

    kb.visibility = visibility
    kb.org_id = org_id
    kb.dept_id = dept_id
    kb.public_dept_ids = public_dept_ids
    if visibility == KBVisibilityEnum.PRIVATE:
        kb.created_by = current_user.id
    kb.updated_by = current_user.id
    kb.updated_at = datetime.now(timezone.utc)

    session.add(kb)
    await session.commit()
    await session.refresh(kb)

    return {
        "id": str(kb.id),
        "name": kb.name,
        "visibility": kb.visibility.value,
        "org_id": str(kb.org_id) if kb.org_id else None,
        "dept_id": str(kb.dept_id) if kb.dept_id else None,
        "public_dept_ids": [str(v) for v in (kb.public_dept_ids or [])],
        "updated_at": kb.updated_at.isoformat(),
    }


@router.delete("/{kb_id}", status_code=HTTPStatus.OK)
async def delete_knowledge_base(
    kb_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: StorageService = Depends(get_storage_service),
):
    kb = (
        await session.exec(
            sm_select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
            )
        )
    ).first()

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if not await _can_delete_knowledge_base(session, current_user, kb):
        raise HTTPException(status_code=403, detail="Not authorized to delete this knowledge base")

    files = (await session.exec(sm_select(UserFile).where(UserFile.knowledge_base_id == kb.id))).all()
    for file in files:
        try:
            storage_path = file.path
            user_prefix = f"{file.user_id}/"
            if storage_path.startswith(user_prefix):
                storage_path = storage_path[len(user_prefix):]
            await storage_service.delete_file(agent_id=str(file.user_id), file_name=storage_path)
        except Exception:
            pass
        await session.delete(file)

    await session.delete(kb)
    await session.commit()
    return {"message": "Knowledge base deleted successfully"}


@router.delete("", status_code=HTTPStatus.OK)
@router.delete("/", status_code=HTTPStatus.OK)
async def delete_knowledge_bases_batch(
    payload: dict,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: StorageService = Depends(get_storage_service),
):
    kb_ids = payload.get("kb_names", [])
    if not isinstance(kb_ids, list) or not kb_ids:
        raise HTTPException(status_code=400, detail="kb_names must be a non-empty list")

    deleted_count = 0
    for raw_id in kb_ids:
        try:
            kb_id = UUID(str(raw_id))
        except Exception:
            continue
        try:
            await delete_knowledge_base(kb_id, current_user, session, storage_service)
            deleted_count += 1
        except HTTPException:
            continue

    return {"deleted_count": deleted_count, "timestamp": datetime.now(timezone.utc).isoformat()}
