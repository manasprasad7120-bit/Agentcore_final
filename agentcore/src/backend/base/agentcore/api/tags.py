"""Tags API – CRUD, predefined tags, search, and usage stats."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.tag.model import (
    PREDEFINED_TAGS,
    AgentTag,
    ProjectTag,
    Tag,
    TagCategoryEnum,
    TagCreate,
    TagRead,
)
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

router = APIRouter(prefix="/tags", tags=["Tags"])


# ── helpers ──────────────────────────────────────────────────────────────

async def _get_user_org_id(session, user_id: UUID) -> UUID | None:
    row = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).first()
    if row is None:
        return None
    return row if isinstance(row, UUID) else row[0]


async def _resolve_or_create_tags(
    session,
    tag_names: list[str],
    org_id: UUID | None,
    user_id: UUID,
) -> list[UUID]:
    """Given a list of tag name strings, return their UUIDs.

    Creates missing custom tags on the fly.
    """
    if not tag_names:
        return []

    # Normalize
    normalized = list({t.strip().lower() for t in tag_names if t.strip()})

    # Fetch existing
    stmt = select(Tag).where(
        Tag.name.in_(normalized),
        or_(Tag.org_id == org_id, Tag.org_id.is_(None)),
    )
    existing = {t.name: t for t in (await session.exec(stmt)).all()}

    tag_ids: list[UUID] = []
    for name in normalized:
        if name in existing:
            tag_ids.append(existing[name].id)
        else:
            new_tag = Tag(
                name=name,
                category=TagCategoryEnum.CUSTOM,
                is_predefined=False,
                org_id=org_id,
                created_by=user_id,
            )
            session.add(new_tag)
            await session.flush()
            tag_ids.append(new_tag.id)

    return tag_ids


async def sync_project_tags(session, project_id: UUID, tag_names: list[str], org_id: UUID | None, user_id: UUID):
    """Replace all tags on a project with the given list."""
    tag_ids = await _resolve_or_create_tags(session, tag_names, org_id, user_id)

    # Remove old associations
    old = (await session.exec(select(ProjectTag).where(ProjectTag.project_id == project_id))).all()
    for pt in old:
        await session.delete(pt)

    # Add new
    for tid in tag_ids:
        session.add(ProjectTag(project_id=project_id, tag_id=tid))


async def sync_agent_tags(session, agent_id: UUID, tag_names: list[str], org_id: UUID | None, user_id: UUID):
    """Replace all tags on an agent with the given list."""
    tag_ids = await _resolve_or_create_tags(session, tag_names, org_id, user_id)

    old = (await session.exec(select(AgentTag).where(AgentTag.agent_id == agent_id))).all()
    for at in old:
        await session.delete(at)

    for tid in tag_ids:
        session.add(AgentTag(agent_id=agent_id, tag_id=tid))


async def get_tags_for_project(session, project_id: UUID) -> list[str]:
    rows = (
        await session.exec(
            select(Tag.name)
            .join(ProjectTag, ProjectTag.tag_id == Tag.id)
            .where(ProjectTag.project_id == project_id)
        )
    ).all()
    return list(rows)


async def get_tags_for_agent(session, agent_id: UUID) -> list[str]:
    rows = (
        await session.exec(
            select(Tag.name)
            .join(AgentTag, AgentTag.tag_id == Tag.id)
            .where(AgentTag.agent_id == agent_id)
        )
    ).all()
    return list(rows)


async def get_tags_for_projects_batch(session, project_ids: list[UUID]) -> dict[UUID, list[str]]:
    """Fetch tags for multiple projects in one query. Returns {project_id: [tag_names]}."""
    if not project_ids:
        return {}
    rows = (
        await session.exec(
            select(ProjectTag.project_id, Tag.name)
            .join(Tag, Tag.id == ProjectTag.tag_id)
            .where(ProjectTag.project_id.in_(project_ids))
        )
    ).all()
    result: dict[UUID, list[str]] = {}
    for proj_id, tag_name in rows:
        result.setdefault(proj_id, []).append(tag_name)
    return result


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/predefined", response_model=list[TagRead], status_code=200)
async def get_predefined_tags(session: DbSession):
    """Return all predefined (system) tags."""
    stmt = select(Tag).where(Tag.is_predefined.is_(True)).order_by(Tag.category, Tag.name)
    tags = (await session.exec(stmt)).all()
    return [TagRead.model_validate(t, from_attributes=True) for t in tags]


@router.get("/search", response_model=list[TagRead], status_code=200)
async def search_tags(
    session: DbSession,
    current_user: CurrentActiveUser,
    q: str = Query("", min_length=0, max_length=60, description="Search query"),
    category: TagCategoryEnum | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    """Autocomplete / search tags visible to the current user's org."""
    org_id = await _get_user_org_id(session, current_user.id)
    stmt = select(Tag).where(or_(Tag.org_id == org_id, Tag.org_id.is_(None)))

    if q:
        stmt = stmt.where(Tag.name.like(f"%{q.lower()}%"))
    if category:
        stmt = stmt.where(Tag.category == category)

    stmt = stmt.order_by(Tag.is_predefined.desc(), Tag.name).limit(limit)
    tags = (await session.exec(stmt)).all()
    return [TagRead.model_validate(t, from_attributes=True) for t in tags]


@router.get("/popular", response_model=list[TagRead], status_code=200)
async def get_popular_tags(
    session: DbSession,
    current_user: CurrentActiveUser,
    limit: int = Query(15, ge=1, le=50),
):
    """Return the most frequently used tags (projects + agents combined)."""
    org_id = await _get_user_org_id(session, current_user.id)

    project_count = (
        select(ProjectTag.tag_id, func.count().label("cnt"))
        .group_by(ProjectTag.tag_id)
        .subquery()
    )
    agent_count = (
        select(AgentTag.tag_id, func.count().label("cnt"))
        .group_by(AgentTag.tag_id)
        .subquery()
    )

    stmt = (
        select(
            Tag,
            (func.coalesce(project_count.c.cnt, 0) + func.coalesce(agent_count.c.cnt, 0)).label("usage_count"),
        )
        .outerjoin(project_count, project_count.c.tag_id == Tag.id)
        .outerjoin(agent_count, agent_count.c.tag_id == Tag.id)
        .where(or_(Tag.org_id == org_id, Tag.org_id.is_(None)))
        .order_by(
            (func.coalesce(project_count.c.cnt, 0) + func.coalesce(agent_count.c.cnt, 0)).desc()
        )
        .limit(limit)
    )

    rows = (await session.exec(stmt)).all()
    result = []
    for tag, usage in rows:
        tag_read = TagRead.model_validate(tag, from_attributes=True)
        tag_read.usage_count = usage
        result.append(tag_read)
    return result


@router.get("/", response_model=list[TagRead], status_code=200)
async def list_tags(
    session: DbSession,
    current_user: CurrentActiveUser,
    category: TagCategoryEnum | None = None,
):
    """List all tags visible to the user's org."""
    org_id = await _get_user_org_id(session, current_user.id)
    stmt = select(Tag).where(or_(Tag.org_id == org_id, Tag.org_id.is_(None)))
    if category:
        stmt = stmt.where(Tag.category == category)
    stmt = stmt.order_by(Tag.category, Tag.name)
    tags = (await session.exec(stmt)).all()
    return [TagRead.model_validate(t, from_attributes=True) for t in tags]


@router.post("/", response_model=TagRead, status_code=201)
async def create_tag(
    session: DbSession,
    current_user: CurrentActiveUser,
    tag: TagCreate,
):
    """Create a custom tag."""
    org_id = await _get_user_org_id(session, current_user.id)
    normalized_name = tag.name.strip().lower()

    # Check uniqueness within org scope
    existing = (
        await session.exec(
            select(Tag).where(
                Tag.name == normalized_name,
                or_(Tag.org_id == org_id, Tag.org_id.is_(None)),
            )
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Tag '{normalized_name}' already exists.")

    new_tag = Tag(
        name=normalized_name,
        category=tag.category,
        description=tag.description,
        is_predefined=False,
        org_id=org_id,
        created_by=current_user.id,
    )
    session.add(new_tag)
    await session.commit()
    await session.refresh(new_tag)
    return TagRead.model_validate(new_tag, from_attributes=True)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    session: DbSession,
    current_user: CurrentActiveUser,
    tag_id: UUID,
):
    """Delete a custom tag. Predefined tags cannot be deleted."""
    tag = (await session.exec(select(Tag).where(Tag.id == tag_id))).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.is_predefined:
        raise HTTPException(status_code=403, detail="Predefined tags cannot be deleted.")

    role = normalize_role(getattr(current_user, "role", None))
    if role not in {"root", "super_admin"} and tag.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to delete this tag.")

    # Cascade handled by FK ondelete, but explicitly clean junction rows for safety
    for pt in (await session.exec(select(ProjectTag).where(ProjectTag.tag_id == tag_id))).all():
        await session.delete(pt)
    for at in (await session.exec(select(AgentTag).where(AgentTag.tag_id == tag_id))).all():
        await session.delete(at)

    await session.delete(tag)
    await session.commit()
