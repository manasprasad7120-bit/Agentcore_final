"""Semantic Search API.

Provides endpoints for:
- Searching entities (projects, agents, models) by semantic similarity
- Backfilling embeddings for existing entities (admin-only)

All search results are filtered by the same role-based visibility rules
as the standard list endpoints — users only see entities they have access to.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlmodel import col, select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent_registry.model import AgentRegistry
from agentcore.services.database.models.model_registry.model import ModelRegistry
from agentcore.services.database.models.project.model import Project
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.semantic_search import backfill_embeddings, semantic_search

router = APIRouter(prefix="/semantic-search", tags=["Semantic Search"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SemanticSearchResponse(BaseModel):
    results: list[dict] = Field(default_factory=list)
    entity_type: str
    query: str
    count: int = 0


class BackfillResponse(BaseModel):
    entity_type: str
    total_entities: int
    vectors_upserted: int


# ---------------------------------------------------------------------------
# Scope helpers (mirrors existing CRUD visibility logic)
# ---------------------------------------------------------------------------


async def _get_scope_memberships(session, user_id: UUID) -> tuple[set[UUID], set[UUID]]:
    """Get user's active org and dept memberships."""
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
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    dept_ids = {r if isinstance(r, UUID) else r[0] for r in dept_rows}
    return org_ids, dept_ids


async def _get_model_dept_pairs(session, user_id: UUID) -> list[tuple[UUID, UUID]]:
    """Get (org_id, dept_id) pairs for model visibility checks."""
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    return [(row[0], row[1]) for row in dept_rows]


def _excluded_higher_role_user_ids(role: str):
    """Return subquery of user IDs whose entities should be hidden from the given role."""
    normalized_db_role = func.lower(func.replace(User.role, " ", "_"))
    if role == "super_admin":
        return select(User.id).where(normalized_db_role.in_(["root"]))
    if role == "department_admin":
        return select(User.id).where(normalized_db_role.in_(["root", "super_admin"]))
    return None


# ---------------------------------------------------------------------------
# Pinecone metadata filter builder
# ---------------------------------------------------------------------------


async def _build_metadata_filter(
    session, current_user, entity_type: str, registry_only: bool,
) -> dict | None:
    """Build a Pinecone metadata filter to pre-scope search results.

    - registry_only=True: filter to only published registry entity IDs
    - For projects/agents: filter by org_id/dept_id based on user role
    """
    role = normalize_role(getattr(current_user, "role", None))

    # Registry-only: scope to published entity IDs
    if registry_only:
        if entity_type == "agents":
            rows = (
                await session.exec(
                    select(AgentRegistry.agent_id).where(
                        AgentRegistry.visibility == "PUBLIC",
                    )
                )
            ).all()
            agent_ids = [str(r) for r in rows]
            if agent_ids:
                return {"entity_id": {"$in": agent_ids}}
            return {"entity_id": {"$in": ["__none__"]}}  # no matches

        if entity_type == "models":
            rows = (await session.exec(select(ModelRegistry.id))).all()
            model_ids = [str(r) for r in rows]
            if model_ids:
                return {"entity_id": {"$in": model_ids}}
            return {"entity_id": {"$in": ["__none__"]}}

    # Non-registry: filter by org/dept for efficiency (root sees all)
    if role == "root":
        return None

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if org_ids:
            return {"org_id": {"$in": [str(o) for o in org_ids]}}

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        visible_user_ids = {str(current_user.id)}
        if dept_ids:
            dept_user_rows = (
                await session.exec(
                    select(UserDepartmentMembership.user_id).where(
                        UserDepartmentMembership.department_id.in_(list(dept_ids)),
                        UserDepartmentMembership.status == "active",
                    )
                )
            ).all()
            for uid in dept_user_rows:
                visible_user_ids.add(str(uid) if not isinstance(uid, str) else uid)
        return {"user_id": {"$in": list(visible_user_ids)}}

    # developer/business_user: filter to own entities only
    return {"user_id": str(current_user.id)}


# ---------------------------------------------------------------------------
# Scoped query builders (replicates existing visibility from projects.py / agent.py)
# ---------------------------------------------------------------------------


async def _build_scoped_project_query(session, current_user, candidate_ids: list[UUID]):
    """Build a scoped Project query filtering candidate IDs by user visibility."""
    role = normalize_role(getattr(current_user, "role", None))
    base = select(Project).where(col(Project.id).in_(candidate_ids))

    if role == "root":
        return base

    own_condition = or_(Project.user_id == current_user.id, Project.owner_user_id == current_user.id)
    excluded_ids = _excluded_higher_role_user_ids(role)

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if org_ids:
            org_user_subquery = select(UserOrganizationMembership.user_id).where(
                UserOrganizationMembership.org_id.in_(list(org_ids)),
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
            stmt = base.where(
                or_(
                    own_condition,
                    Project.org_id.in_(list(org_ids)),
                    Project.user_id.in_(org_user_subquery),
                    Project.owner_user_id.in_(org_user_subquery),
                )
            )
            if excluded_ids is not None:
                stmt = stmt.where(~Project.user_id.in_(excluded_ids))
            return stmt
        return base.where(own_condition)

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if dept_ids:
            dept_user_subquery = select(UserDepartmentMembership.user_id).where(
                UserDepartmentMembership.department_id.in_(list(dept_ids)),
                UserDepartmentMembership.status == "active",
            )
            stmt = base.where(
                or_(
                    own_condition,
                    Project.dept_id.in_(list(dept_ids)),
                    Project.user_id.in_(dept_user_subquery),
                    Project.owner_user_id.in_(dept_user_subquery),
                )
            )
            if excluded_ids is not None:
                stmt = stmt.where(~Project.user_id.in_(excluded_ids))
            return stmt
        return base.where(own_condition)

    # developer / business_user — only own projects
    return base.where(own_condition)


async def _build_scoped_agent_query(session, current_user, candidate_ids: list[UUID]):
    """Build a scoped Agent query filtering candidate IDs by user visibility."""
    role = normalize_role(getattr(current_user, "role", None))
    base = select(Agent).where(
        col(Agent.id).in_(candidate_ids),
        Agent.deleted_at.is_(None),  # type: ignore[union-attr]
    )

    if role == "root":
        return base

    own_condition = Agent.user_id == current_user.id

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if org_ids:
            org_user_subquery = select(UserOrganizationMembership.user_id).where(
                UserOrganizationMembership.org_id.in_(list(org_ids)),
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
            return base.where(
                or_(
                    own_condition,
                    Agent.org_id.in_(list(org_ids)),
                    Agent.user_id.in_(org_user_subquery),
                )
            )
        return base.where(own_condition)

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if dept_ids:
            dept_user_subquery = select(UserDepartmentMembership.user_id).where(
                UserDepartmentMembership.department_id.in_(list(dept_ids)),
                UserDepartmentMembership.status == "active",
            )
            return base.where(
                or_(
                    own_condition,
                    Agent.dept_id.in_(list(dept_ids)),
                    Agent.user_id.in_(dept_user_subquery),
                )
            )
        return base.where(own_condition)

    # developer / business_user — only own agents
    return base.where(own_condition)


def _can_access_model(
    row: ModelRegistry,
    current_user,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    """Check if user can see this model (mirrors model_registry._can_access_model)."""
    role = normalize_role(str(current_user.role))
    user_id = str(current_user.id)

    if role == "root":
        return True
    if not row.org_id:
        return False

    if role == "super_admin" and row.org_id in org_ids:
        return True

    # Non-approved models: only requester or approver
    approval_status = getattr(row, "approval_status", "approved") or "approved"
    if approval_status != "approved":
        return str(row.requested_by or "") == user_id or str(row.request_to or "") == user_id

    visibility_scope = (getattr(row, "visibility_scope", None) or "private").lower()

    if visibility_scope == "private":
        if role == "department_admin":
            dept_ids = {str(d) for _, d in dept_pairs}
            return bool(row.dept_id and str(row.dept_id) in dept_ids)
        return (
            str(getattr(row, "created_by_id", "") or "") == user_id
            or str(row.requested_by or "") == user_id
        )

    if visibility_scope == "department":
        dept_ids = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if row.dept_id and str(row.dept_id) in dept_ids:
            return True
        return bool(scoped_public_depts.intersection(dept_ids))

    if visibility_scope == "organization":
        return bool(row.org_id and row.org_id in org_ids)

    return False


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------


@router.get("/search", response_model=SemanticSearchResponse)
async def search(
    session: DbSession,
    current_user: CurrentActiveUser,
    entity_type: str = Query(..., pattern="^(projects|agents|models)$"),
    q: str = Query(..., min_length=1, max_length=1000),
    top_k: int = Query(default=20, ge=1, le=100),
    registry_only: bool = Query(default=False),
):
    """Semantic search across projects, agents, or models.

    Results are filtered by the same role-based visibility rules as
    the standard list endpoints. Users only see entities they have access to.

    When ``registry_only=True``, search is scoped to published registry entries
    via Pinecone metadata filtering.
    """
    # Build metadata filter for Pinecone pre-filtering
    metadata_filter = await _build_metadata_filter(
        session, current_user, entity_type, registry_only,
    )

    # Step 1: Get semantic results (with optional metadata pre-filtering)
    try:
        hits = await semantic_search(
            entity_type=entity_type,
            query=q,
            top_k=min(top_k * 3, 100),  # over-fetch to account for post-filtering
            metadata_filter=metadata_filter,
        )
    except Exception:
        logger.warning("[SEMANTIC] Search failed for entity_type=%s query='%s', returning empty results", entity_type, q, exc_info=True)
        hits = []

    if not hits:
        return SemanticSearchResponse(results=[], entity_type=entity_type, query=q, count=0)

    entity_ids = [h["entity_id"] for h in hits if h.get("entity_id")]
    score_map = {h["entity_id"]: h["score"] for h in hits}

    # Step 2: Fetch from DB with proper user-scoped visibility filtering
    results: list[dict] = []

    if entity_type == "projects":
        uuid_ids = [UUID(eid) for eid in entity_ids]
        stmt = await _build_scoped_project_query(session, current_user, uuid_ids)
        rows = (await session.exec(stmt)).all()
        row_map = {str(r.id): r for r in rows}
        for eid in entity_ids:
            if eid in row_map:
                r = row_map[eid]
                results.append({
                    "id": str(r.id),
                    "name": r.name,
                    "description": r.description,
                    "score": score_map.get(eid, 0.0),
                })
            if len(results) >= top_k:
                break

    elif entity_type == "agents":
        uuid_ids = [UUID(eid) for eid in entity_ids]
        stmt = await _build_scoped_agent_query(session, current_user, uuid_ids)
        rows = (await session.exec(stmt)).all()
        row_map = {str(r.id): r for r in rows}
        for eid in entity_ids:
            if eid in row_map:
                r = row_map[eid]
                results.append({
                    "id": str(r.id),
                    "name": r.name,
                    "description": r.description,
                    "tags": r.tags,
                    "score": score_map.get(eid, 0.0),
                })
            if len(results) >= top_k:
                break

    elif entity_type == "models":
        uuid_ids = [UUID(eid) for eid in entity_ids]
        # For models, fetch all candidates then apply per-row access check
        stmt = select(ModelRegistry).where(col(ModelRegistry.id).in_(uuid_ids))
        rows = (await session.exec(stmt)).all()
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        dept_pairs = await _get_model_dept_pairs(session, current_user.id)
        row_map = {str(r.id): r for r in rows}
        for eid in entity_ids:
            if eid in row_map:
                r = row_map[eid]
                if _can_access_model(r, current_user, org_ids, dept_pairs):
                    results.append({
                        "id": str(r.id),
                        "name": r.display_name,
                        "description": r.description,
                        "provider": r.provider,
                        "model_name": r.model_name,
                        "model_type": r.model_type,
                        "score": score_map.get(eid, 0.0),
                    })
            if len(results) >= top_k:
                break

    return SemanticSearchResponse(
        results=results,
        entity_type=entity_type,
        query=q,
        count=len(results),
    )


# ---------------------------------------------------------------------------
# Backfill endpoint (admin)
# ---------------------------------------------------------------------------


@router.post("/backfill/{entity_type}", response_model=BackfillResponse)
async def backfill(
    entity_type: str,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Backfill semantic search embeddings for all entities of a given type.

    Admin-only operation. Idempotent — safe to re-run.
    """
    if entity_type not in ("projects", "agents", "models"):
        raise HTTPException(status_code=400, detail=f"Invalid entity_type: {entity_type}")

    role = normalize_role(getattr(current_user, "role", None))
    if role not in ("root", "super_admin"):
        raise HTTPException(status_code=403, detail="Only admin users can run backfill")

    entities: list[dict] = []

    if entity_type == "projects":
        rows = (await session.exec(select(Project))).all()
        for r in rows:
            entities.append({
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "tags": [],
                "org_id": str(r.org_id) if r.org_id else None,
                "dept_id": str(r.dept_id) if r.dept_id else None,
            })

    elif entity_type == "agents":
        rows = (await session.exec(
            select(Agent).where(Agent.deleted_at.is_(None))  # type: ignore[union-attr]
        )).all()
        for r in rows:
            entities.append({
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "tags": r.tags if isinstance(r.tags, list) else [],
                "org_id": str(r.org_id) if r.org_id else None,
                "dept_id": str(r.dept_id) if r.dept_id else None,
            })

    elif entity_type == "models":
        rows = (await session.exec(select(ModelRegistry))).all()
        for r in rows:
            entities.append({
                "id": str(r.id),
                "name": r.display_name,
                "description": r.description,
                "tags": [r.provider, r.model_name] if r.provider else [],
                "org_id": str(r.org_id) if getattr(r, "org_id", None) else None,
                "dept_id": str(r.dept_id) if getattr(r, "dept_id", None) else None,
            })

    total = len(entities)
    logger.info("[SEMANTIC] Backfill started for %s: %d entities", entity_type, total)

    upserted = await backfill_embeddings(entity_type, entities)

    return BackfillResponse(
        entity_type=entity_type,
        total_entities=total,
        vectors_upserted=upserted,
    )
