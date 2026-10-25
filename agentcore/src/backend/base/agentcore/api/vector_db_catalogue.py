from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, tuple_
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.vector_db_catalogue.model import VectorDBCatalogue
from agentcore.services.auth.permissions import get_permissions_for_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vector-db-catalogue", tags=["Vector DB Catalogue"])


class VectorDBPayload(BaseModel):
    name: str
    description: str | None = None
    provider: str
    deployment: str
    dimensions: str
    indexType: str
    status: str = "connected"
    vectorCount: str = "0"
    isCustom: bool = False
    org_id: UUID | None = None
    dept_id: UUID | None = None
    environment: str = "uat"
    index_name: str | None = None
    namespace: str | None = None
    agent_id: UUID | None = None
    agent_name: str | None = None


class TrackMigrationPayload(BaseModel):
    """Payload used by the approval hook to auto-track a Pinecone UAT→PROD migration."""
    source_entry_id: UUID | None = None
    name: str
    provider: str = "Pinecone"
    deployment: str = "SaaS"
    dimensions: str = ""
    index_name: str
    source_namespace: str
    target_namespace: str
    vectors_copied: int = 0
    agent_id: UUID | None = None
    agent_name: str | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


async def _require_vector_db_permission(current_user: CurrentActiveUser, permission: str) -> None:
    if _is_root_user(current_user):
        return
    user_permissions = await get_permissions_for_role(str(current_user.role))
    if permission not in user_permissions:
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


async def _visibility_filters(session: DbSession, current_user: CurrentActiveUser):
    if _is_root_user(current_user):
        return []

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    filters = [and_(VectorDBCatalogue.org_id.is_(None), VectorDBCatalogue.dept_id.is_(None))]

    if org_ids:
        filters.append(and_(VectorDBCatalogue.org_id.in_(list(org_ids)), VectorDBCatalogue.dept_id.is_(None)))

    if dept_pairs:
        filters.append(tuple_(VectorDBCatalogue.org_id, VectorDBCatalogue.dept_id).in_(dept_pairs))

    return filters


async def _validate_scope_refs(session: DbSession, payload) -> None:
    org_id = getattr(payload, "org_id", None)
    dept_id = getattr(payload, "dept_id", None)

    if dept_id and not org_id:
        raise HTTPException(status_code=400, detail="dept_id requires org_id")

    if org_id:
        org = await session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=400, detail="Invalid org_id")

    if dept_id:
        dept = (
            await session.exec(
                select(Department).where(
                    Department.id == dept_id,
                    Department.org_id == org_id,
                )
            )
        ).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Invalid dept_id for org_id")


def _serialize_vector_db(row: VectorDBCatalogue) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "provider": row.provider,
        "deployment": row.deployment,
        "dimensions": row.dimensions,
        "indexType": row.index_type,
        "status": row.status,
        "vectorCount": row.vector_count,
        "isCustom": bool(row.is_custom),
        "org_id": str(row.org_id) if row.org_id else None,
        "dept_id": str(row.dept_id) if row.dept_id else None,
        # New Pinecone tracking fields
        "environment": row.environment or "uat",
        "indexName": row.index_name or "",
        "namespace": row.namespace or "",
        "agentId": str(row.agent_id) if row.agent_id else None,
        "agentName": row.agent_name or "",
        "sourceEntryId": str(row.source_entry_id) if row.source_entry_id else None,
        "migrationStatus": row.migration_status or "",
        "migratedAt": row.migrated_at.isoformat() if row.migrated_at else None,
        "vectorsCopied": row.vectors_copied or 0,
    }


@router.get("")
@router.get("/")
async def list_vector_db_catalogue(
    current_user: CurrentActiveUser,
    session: DbSession,
    environment: str | None = Query(None, description="Filter by environment: uat, prod"),
) -> list[dict]:
    filters = await _visibility_filters(session, current_user)
    query = select(VectorDBCatalogue).order_by(VectorDBCatalogue.name.asc())
    if filters:
        query = query.where(or_(*filters))
    if environment:
        query = query.where(VectorDBCatalogue.environment == environment.lower())

    rows = (await session.exec(query)).all()
    return [_serialize_vector_db(row) for row in rows]


@router.post("")
@router.post("/")
async def create_vector_db_catalogue(
    payload: VectorDBPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    await _validate_scope_refs(session, payload)
    now = datetime.now(timezone.utc)
    row = VectorDBCatalogue(
        name=payload.name,
        description=payload.description,
        provider=payload.provider,
        deployment=payload.deployment,
        dimensions=payload.dimensions,
        index_type=payload.indexType,
        status=payload.status,
        vector_count=payload.vectorCount,
        is_custom=payload.isCustom,
        org_id=payload.org_id,
        dept_id=payload.dept_id,
        environment=payload.environment or "uat",
        index_name=payload.index_name,
        namespace=payload.namespace,
        agent_id=payload.agent_id,
        agent_name=payload.agent_name,
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=now,
        updated_at=now,
        published_by=current_user.id if payload.status == "connected" else None,
        published_at=now if payload.status == "connected" else None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize_vector_db(row)


@router.patch("/{vector_db_id}")
async def update_vector_db_catalogue(
    vector_db_id: UUID,
    payload: VectorDBPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    row = await session.get(VectorDBCatalogue, vector_db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vector DB entry not found")

    await _validate_scope_refs(session, payload)
    now = datetime.now(timezone.utc)

    row.name = payload.name
    row.description = payload.description
    row.provider = payload.provider
    row.deployment = payload.deployment
    row.dimensions = payload.dimensions
    row.index_type = payload.indexType
    row.status = payload.status
    row.vector_count = payload.vectorCount
    row.is_custom = payload.isCustom
    row.org_id = payload.org_id
    row.dept_id = payload.dept_id
    row.environment = payload.environment or row.environment
    row.index_name = payload.index_name or row.index_name
    row.namespace = payload.namespace or row.namespace
    row.agent_id = payload.agent_id or row.agent_id
    row.agent_name = payload.agent_name or row.agent_name
    row.updated_by = current_user.id
    row.updated_at = now
    if payload.status == "connected":
        row.published_by = current_user.id
        row.published_at = now

    await session.commit()
    await session.refresh(row)
    return _serialize_vector_db(row)


@router.delete("/{vector_db_id}")
async def delete_vector_db_catalogue(
    vector_db_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_vector_db_permission(current_user, "delete_vector_db_catalogue")
    row = await session.get(VectorDBCatalogue, vector_db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vector DB entry not found")

    await session.delete(row)
    await session.commit()
    return {"message": "Vector DB entry deleted successfully"}


# ---------------------------------------------------------------------------
# Track migration (called internally by approval hook)
# ---------------------------------------------------------------------------


@router.post("/track-migration")
async def track_migration(
    payload: TrackMigrationPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Record a Pinecone namespace migration in the catalogue.

    Called automatically after UAT→PROD approval copies vectors.
    Creates a new PROD entry linked to the source UAT entry.
    """
    now = datetime.now(timezone.utc)

    # Try to find existing UAT entry by index_name + namespace
    uat_entry = None
    if payload.source_entry_id:
        uat_entry = await session.get(VectorDBCatalogue, payload.source_entry_id)
    if not uat_entry:
        result = await session.exec(
            select(VectorDBCatalogue).where(
                VectorDBCatalogue.index_name == payload.index_name,
                VectorDBCatalogue.namespace == payload.source_namespace,
                VectorDBCatalogue.environment == "uat",
            ).limit(1)
        )
        uat_entry = result.first()

    prod_row = VectorDBCatalogue(
        name=f"{payload.name} (PROD)",
        description=f"PROD copy from UAT namespace '{payload.source_namespace}'",
        provider=payload.provider,
        deployment=payload.deployment,
        dimensions=payload.dimensions or (uat_entry.dimensions if uat_entry else ""),
        index_type=uat_entry.index_type if uat_entry else "serverless",
        status="connected",
        vector_count=str(payload.vectors_copied),
        is_custom=False,
        environment="prod",
        index_name=payload.index_name,
        namespace=payload.target_namespace,
        agent_id=payload.agent_id,
        agent_name=payload.agent_name,
        source_entry_id=uat_entry.id if uat_entry else None,
        migration_status="completed",
        migrated_at=now,
        vectors_copied=payload.vectors_copied,
        org_id=payload.org_id or (uat_entry.org_id if uat_entry else None),
        dept_id=payload.dept_id or (uat_entry.dept_id if uat_entry else None),
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=now,
        updated_at=now,
        published_by=current_user.id,
        published_at=now,
    )
    session.add(prod_row)
    await session.commit()
    await session.refresh(prod_row)

    logger.info(
        "[VECTOR_DB_TRACK] PROD entry created: id=%s index=%s ns=%s vectors=%d",
        prod_row.id, payload.index_name, payload.target_namespace, payload.vectors_copied,
    )
    return _serialize_vector_db(prod_row)


@router.get("/{vector_db_id}/lineage")
async def get_lineage(
    vector_db_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Get UAT→PROD lineage for a vector DB entry."""
    row = await session.get(VectorDBCatalogue, vector_db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vector DB entry not found")

    result = {"entry": _serialize_vector_db(row), "source": None, "prod_copies": []}

    # If this is a PROD entry, get the UAT source
    if row.source_entry_id:
        source = await session.get(VectorDBCatalogue, row.source_entry_id)
        if source:
            result["source"] = _serialize_vector_db(source)

    # Find any PROD entries that were copied from this UAT entry
    prod_rows = (
        await session.exec(
            select(VectorDBCatalogue).where(
                VectorDBCatalogue.source_entry_id == vector_db_id,
            ).order_by(VectorDBCatalogue.migrated_at.desc())
        )
    ).all()
    result["prod_copies"] = [_serialize_vector_db(r) for r in prod_rows]

    return result


# ---------------------------------------------------------------------------
# Live Pinecone index management (proxied through pinecone-service)
# ---------------------------------------------------------------------------


class DeleteIndexPayload(BaseModel):
    index_name: str


class DeleteNamespacePayload(BaseModel):
    index_name: str
    namespace: str


@router.get("/pinecone/indexes")
async def list_pinecone_indexes(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """List all live Pinecone indexes with namespaces, vector counts, and agent usage.

    Merges live data from pinecone-service with catalogue entries to show
    which agent uses each index/namespace.
    """
    from agentcore.services.pinecone_service_client import (
        is_service_configured,
        list_indexes_via_service,
    )

    if not is_service_configured():
        raise HTTPException(status_code=400, detail="Pinecone service is not configured")

    try:
        live_data = list_indexes_via_service()
    except Exception as e:
        logger.error("Failed to list Pinecone indexes: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list indexes: {e}")

    # Load catalogue entries to enrich with agent info
    catalogue_rows = (
        await session.exec(
            select(VectorDBCatalogue).where(
                VectorDBCatalogue.provider == "Pinecone",
            )
        )
    ).all()

    # Build lookup: (index_name, namespace) → catalogue entry
    catalogue_map: dict[tuple[str, str], dict] = {}
    for row in catalogue_rows:
        key = (row.index_name or "", row.namespace or "")
        catalogue_map[key] = {
            "catalogueId": str(row.id),
            "agentId": str(row.agent_id) if row.agent_id else None,
            "agentName": row.agent_name or "",
            "environment": row.environment or "",
            "migrationStatus": row.migration_status or "",
        }

    # Enrich live indexes with catalogue data
    indexes = live_data.get("indexes", [])
    for idx in indexes:
        idx_name = idx.get("name", "")
        enriched_namespaces = []
        for ns in idx.get("namespaces", []):
            ns_info = {"namespace": ns}
            cat = catalogue_map.get((idx_name, ns))
            if cat:
                ns_info.update(cat)
            enriched_namespaces.append(ns_info)
        idx["enriched_namespaces"] = enriched_namespaces

    return live_data


@router.post("/pinecone/delete-index")
async def delete_pinecone_index(
    payload: DeleteIndexPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Delete a Pinecone index and remove all related catalogue entries."""
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    from agentcore.services.pinecone_service_client import (
        delete_index_via_service,
        is_service_configured,
    )

    if not is_service_configured():
        raise HTTPException(status_code=400, detail="Pinecone service is not configured")

    # Delete from Pinecone
    try:
        result = delete_index_via_service(payload.index_name)
    except Exception as e:
        logger.error("Failed to delete Pinecone index '%s': %s", payload.index_name, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete index: {e}")

    # Remove catalogue entries for this index
    cat_rows = (
        await session.exec(
            select(VectorDBCatalogue).where(
                VectorDBCatalogue.index_name == payload.index_name,
                VectorDBCatalogue.provider == "Pinecone",
            )
        )
    ).all()
    for row in cat_rows:
        await session.delete(row)
    await session.commit()

    return {
        **result,
        "catalogue_entries_removed": len(cat_rows),
    }


@router.post("/pinecone/delete-namespace")
async def delete_pinecone_namespace(
    payload: DeleteNamespacePayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Delete a Pinecone namespace and remove related catalogue entries."""
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    from agentcore.services.pinecone_service_client import (
        delete_namespace_via_service,
        is_service_configured,
    )

    if not is_service_configured():
        raise HTTPException(status_code=400, detail="Pinecone service is not configured")

    # Delete from Pinecone
    try:
        result = delete_namespace_via_service(payload.index_name, payload.namespace)
    except Exception as e:
        logger.error(
            "Failed to delete namespace '%s' from index '%s': %s",
            payload.namespace, payload.index_name, e,
        )
        raise HTTPException(status_code=500, detail=f"Failed to delete namespace: {e}")

    # Remove catalogue entries for this namespace
    cat_rows = (
        await session.exec(
            select(VectorDBCatalogue).where(
                VectorDBCatalogue.index_name == payload.index_name,
                VectorDBCatalogue.namespace == payload.namespace,
                VectorDBCatalogue.provider == "Pinecone",
            )
        )
    ).all()
    for row in cat_rows:
        await session.delete(row)
    await session.commit()

    return {
        **result,
        "catalogue_entries_removed": len(cat_rows),
    }


@router.get("/agent-usage/{agent_id}")
async def get_agent_vdb_usage(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    """Get all VDB catalogue entries (indexes/namespaces) used by a specific agent."""
    rows = (
        await session.exec(
            select(VectorDBCatalogue).where(
                VectorDBCatalogue.agent_id == agent_id,
            ).order_by(VectorDBCatalogue.environment.asc(), VectorDBCatalogue.index_name.asc())
        )
    ).all()
    return [_serialize_vector_db(row) for row in rows]
