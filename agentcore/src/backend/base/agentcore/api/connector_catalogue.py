from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue

router = APIRouter(prefix="/connector-catalogue", tags=["Connector Catalogue"])

DB_PROVIDERS = {"postgresql", "oracle", "sqlserver", "mysql"}
STORAGE_PROVIDERS = {"azure_blob", "sharepoint"}
EMAIL_PROVIDERS = {"outlook"}


# ---------- Key Vault helpers ----------

_KV_STORE = None

def _get_kv_store():
    global _KV_STORE
    if _KV_STORE is not None:
        return _KV_STORE
    from agentcore.services.settings.key_vault import KeyVaultConfig, KeyVaultSecretStore

    vault_url = os.getenv("AGENTCORE_KEY_VAULT_URL", "").strip()
    if not vault_url:
        raise HTTPException(status_code=500, detail="Azure Key Vault is not configured")

    kv_store = KeyVaultSecretStore.from_config(
        KeyVaultConfig(
            vault_url=vault_url,
            secret_prefix=os.getenv("AGENTCORE_KEY_VAULT_SECRET_PREFIX", "agentcore").strip() or "agentcore",
        )
    )
    if kv_store is None:
        raise HTTPException(status_code=500, detail="Azure Key Vault client is not initialized")
    _KV_STORE = kv_store
    return kv_store


def _secret_prefix() -> str:
    prefix = os.getenv("AGENTCORE_KEY_VAULT_SECRET_PREFIX", "agentcore").strip()
    return prefix or "agentcore"


def _build_secret_name(prefix: str, connector_id: UUID, provider: str, key: str) -> str:
    provider_tag = provider.replace("_", "-")
    return f"{prefix}-connector-{provider_tag}-{connector_id}-{key}"


def _store_secret_value(name: str, value: str) -> None:
    if not value:
        return
    store = _get_kv_store()
    store.set_secret(name, value)


def _resolve_secret_value(name: str) -> str:
    if not name:
        return ""
    store = _get_kv_store()
    secret_value = store.get_secret(name) or ""
    if not secret_value:
        raise HTTPException(status_code=500, detail=f"Key Vault secret '{name}' not found")
    return secret_value


def _prepare_provider_config(
    provider: str,
    config: dict,
    *,
    connector_id: UUID,
    existing_config: dict | None = None,
    allow_secret_update: bool = True,
) -> dict:
    """Store secrets in Key Vault and persist secret references in provider_config."""
    prepared = dict(config or {})
    existing = dict(existing_config or {})
    prefix = _secret_prefix()

    if provider == "azure_blob":
        # Azure Blob connectors use managed identity (AAD) only.
        # Strip legacy connection-string fields if present.
        prepared.pop("connection_string", None)
        prepared.pop("connection_string_secret_name", None)

    elif provider == "sharepoint":
        secret_name_key = "client_secret_secret_name"
        raw_value = prepared.get("client_secret")
        if raw_value:
            if allow_secret_update or not existing.get(secret_name_key):
                secret_name = _build_secret_name(prefix, connector_id, provider, "client-secret")
                _store_secret_value(secret_name, raw_value)
                prepared[secret_name_key] = secret_name
            else:
                prepared[secret_name_key] = existing.get(secret_name_key) or prepared.get(secret_name_key)
            prepared.pop("client_secret", None)
        elif existing.get(secret_name_key):
            prepared[secret_name_key] = existing[secret_name_key]

    elif provider in EMAIL_PROVIDERS:
        secret_name_key = "client_secret_secret_name"
        raw_value = prepared.get("client_secret")
        if raw_value:
            if allow_secret_update or not existing.get(secret_name_key):
                secret_name = _build_secret_name(prefix, connector_id, provider, "client-secret")
                _store_secret_value(secret_name, raw_value)
                prepared[secret_name_key] = secret_name
            else:
                prepared[secret_name_key] = existing.get(secret_name_key) or prepared.get(secret_name_key)
            prepared.pop("client_secret", None)
        elif existing.get(secret_name_key):
            prepared[secret_name_key] = existing[secret_name_key]

    return prepared


def _ensure_provider_secret_present(provider: str, config: dict, existing_config: dict | None = None) -> None:
    existing = dict(existing_config or {})
    if provider == "azure_blob":
        merged = {**existing, **(config or {})}
        if merged.get("connection_string") or merged.get("connection_string_secret_name"):
            raise HTTPException(
                status_code=400,
                detail="connection_string is no longer supported for Azure Blob connector. Use account_url + container_name.",
            )
        if not merged.get("account_url"):
            raise HTTPException(status_code=400, detail="account_url is required for Azure Blob connector")
        if not merged.get("container_name"):
            raise HTTPException(status_code=400, detail="container_name is required for Azure Blob connector")
    elif provider == "sharepoint":
        if not config.get("client_secret") and not config.get("client_secret_secret_name") and not existing.get("client_secret_secret_name"):
            raise HTTPException(status_code=400, detail="client_secret is required for SharePoint connector")
    elif provider in EMAIL_PROVIDERS:
        if not config.get("client_secret") and not config.get("client_secret_secret_name") and not existing.get("client_secret_secret_name"):
            raise HTTPException(status_code=400, detail="client_secret is required for Outlook connector")


def _decrypt_provider_config(provider: str, config: dict) -> dict:
    """Resolve Key Vault secrets into provider_config for runtime use."""
    resolved = dict(config or {})
    if provider == "azure_blob":
        # Azure Blob uses managed identity only; no provider secrets to resolve.
        resolved.pop("connection_string", None)
        resolved.pop("connection_string_secret_name", None)
    elif provider == "sharepoint":
        if "client_secret" not in resolved:
            secret_name = resolved.get("client_secret_secret_name", "")
            if secret_name:
                resolved["client_secret"] = _resolve_secret_value(secret_name)
    elif provider in EMAIL_PROVIDERS:
        if "client_secret" not in resolved:
            secret_name = resolved.get("client_secret_secret_name", "")
            if secret_name:
                resolved["client_secret"] = _resolve_secret_value(secret_name)
    return resolved


# ---------- Payloads ----------

class ConnectorPayload(BaseModel):
    name: str
    description: str | None = None
    provider: str  # postgresql | oracle | sqlserver | mysql | azure_blob | sharepoint
    # DB-only fields (optional for non-DB providers)
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    schema_name: str = "public"
    username: str | None = None
    password: str | None = None
    ssl_enabled: bool = False
    # Non-DB provider config (Azure Blob, SharePoint)
    provider_config: dict | None = None
    is_custom: bool = False
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str = "private"  # private | public
    public_scope: str | None = None  # organization | department (required when visibility=public)
    public_dept_ids: list[UUID] | None = None  # super_admin can select multiple departments


class ConnectorUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None
    provider: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    schema_name: str | None = None
    username: str | None = None
    password: str | None = None
    ssl_enabled: bool | None = None
    provider_config: dict | None = None
    is_custom: bool | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str | None = None
    public_scope: str | None = None
    public_dept_ids: list[UUID] | None = None


class TestConnectionPayload(BaseModel):
    provider: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    schema_name: str | None = None
    username: str | None = None
    password: str | None = None
    ssl_enabled: bool | None = None
    provider_config: dict | None = None


# ---------- RBAC helpers (same pattern as VectorDB) ----------

def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


async def _require_connector_permission(current_user: CurrentActiveUser, permission: str) -> None:
    user_permissions = await get_permissions_for_role(str(current_user.role))
    if permission not in user_permissions:
        raise HTTPException(status_code=403, detail="Missing required permissions")


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


def _string_ids(values: list[UUID] | None) -> list[str]:
    return [str(v) for v in (values or [])]


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


async def _ensure_connector_name_available(
    session: DbSession,
    name: str,
    org_id: UUID | None,
    dept_id: UUID | None,
    *,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(ConnectorCatalogue.id).where(
        func.lower(ConnectorCatalogue.name) == name.strip().lower(),
    )
    stmt = stmt.where(
        ConnectorCatalogue.org_id.is_(None) if org_id is None else ConnectorCatalogue.org_id == org_id,
    )
    stmt = stmt.where(
        ConnectorCatalogue.dept_id.is_(None) if dept_id is None else ConnectorCatalogue.dept_id == dept_id,
    )
    if exclude_id:
        stmt = stmt.where(ConnectorCatalogue.id != exclude_id)
    existing = (await session.exec(stmt)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Connector name already exists for this scope")


# ---------- Serialization ----------

def _serialize_connector(
    row: ConnectorCatalogue,
    created_by_lookup: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    # Return provider_config with secrets masked (not decrypted) for display
    safe_config: dict | None = None
    if row.provider_config:
        safe_config = dict(row.provider_config)
        if row.provider == "azure_blob":
            if "connection_string" in safe_config:
                safe_config["connection_string"] = "********"
            if "connection_string_secret_name" in safe_config:
                safe_config["connection_string_secret_name"] = "********"
        elif row.provider == "sharepoint":
            if "client_secret" in safe_config:
                safe_config["client_secret"] = "********"
            if "client_secret_secret_name" in safe_config:
                safe_config["client_secret_secret_name"] = "********"
        elif row.provider in EMAIL_PROVIDERS:
            for key in ("client_secret", "access_token", "refresh_token"):
                if key in safe_config:
                    safe_config[key] = "********"
            if "linked_accounts" in safe_config:
                safe_config["linked_accounts"] = [dict(acct) for acct in safe_config["linked_accounts"]]
                for acct in safe_config["linked_accounts"]:
                    for key in ("access_token", "refresh_token"):
                        if key in acct:
                            acct[key] = "********"
            if "client_secret_secret_name" in safe_config:
                safe_config["client_secret_secret_name"] = "********"

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "provider": row.provider,
        "host": row.host,
        "port": row.port,
        "database_name": row.database_name,
        "schema_name": row.schema_name,
        "username": row.username,
        "ssl_enabled": row.ssl_enabled,
        "provider_config": safe_config,
        "status": row.status,
        "tables_metadata": row.tables_metadata,
        "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
        "isCustom": bool(row.is_custom),
        "org_id": str(row.org_id) if row.org_id else None,
        "dept_id": str(row.dept_id) if row.dept_id else None,
        "visibility": row.visibility,
        "public_scope": row.public_scope,
        "public_dept_ids": row.public_dept_ids or [],
        "shared_user_ids": row.shared_user_ids or [],
        "created_by": (created_by_lookup or {}).get(str(row.created_by), {}).get("display") if row.created_by else None,
        "created_by_email": (created_by_lookup or {}).get(str(row.created_by), {}).get("email") if row.created_by else None,
        "created_by_id": str(row.created_by) if row.created_by else None,
    }


def _creator_display_name(display_name: str | None, email: str | None, username: str | None) -> str | None:
    name = str(display_name or "").strip()
    if name:
        return name
    normalized_email = str(email or "").strip()
    if normalized_email:
        return normalized_email.split("@", 1)[0] if "@" in normalized_email else normalized_email
    normalized_username = str(username or "").strip()
    if normalized_username:
        return normalized_username.split("@", 1)[0] if "@" in normalized_username else normalized_username
    return None


def _creator_email(email: str | None, username: str | None) -> str | None:
    normalized_email = str(email or "").strip()
    if normalized_email:
        return normalized_email
    normalized_username = str(username or "").strip()
    if normalized_username and "@" in normalized_username:
        return normalized_username
    return None


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


async def _enforce_creation_scope(
    session: DbSession,
    current_user: CurrentActiveUser,
    payload: ConnectorPayload | ConnectorUpdatePayload,
) -> tuple[str, str | None, list[str], list[str]]:
    user_role = normalize_role(str(current_user.role))
    visibility = _normalize_visibility(getattr(payload, "visibility", None))
    public_scope = _normalize_public_scope(getattr(payload, "public_scope", None))
    public_dept_ids = _string_ids(getattr(payload, "public_dept_ids", None))
    shared_user_ids: list[str] = []
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    dept_ids = {dept_id for _, dept_id in dept_pairs}

    if user_role not in {"root", "super_admin", "department_admin", "developer", "business_user"}:
        raise HTTPException(status_code=403, detail="Your role is not allowed to create connectors")

    if visibility == "private":
        payload.public_scope = None
        payload.public_dept_ids = None
        if user_role == "root":
            payload.org_id = None
            payload.dept_id = None
        elif user_role == "super_admin":
            if not org_ids:
                raise HTTPException(status_code=403, detail="No active organization scope found")
            payload.org_id = sorted(org_ids, key=str)[0]
            payload.dept_id = None
        elif user_role in {"department_admin", "developer", "business_user"}:
            if not dept_pairs:
                raise HTTPException(status_code=403, detail="No active department scope found")
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            payload.org_id = current_org_id
            payload.dept_id = current_dept_id
        else:
            payload.org_id = None
            payload.dept_id = None
        shared_user_ids = []
    else:
        # public
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
                # non-super-admin can only publish to their own current department
                current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
                payload.org_id = current_org_id
                payload.dept_id = current_dept_id
                public_dept_ids = [str(current_dept_id)]
        shared_user_ids = []

    await _validate_scope_refs(session, payload.org_id, payload.dept_id)
    return visibility, public_scope, public_dept_ids, shared_user_ids


def _can_access_connector(
    row: ConnectorCatalogue,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        # Root should not see tenant/user connectors from org/dept admins or users.
        # Keep root visibility limited to root-owned global connectors.
        return (
            str(getattr(row, "created_by", "")) == str(current_user.id)
            and row.org_id is None
            and row.dept_id is None
        )

    role = normalize_role(str(current_user.role))
    # Super admins can view any connector that belongs to organizations they administer.
    if role == "super_admin" and row.org_id and row.org_id in org_ids:
        return True

    visibility = _normalize_visibility(getattr(row, "visibility", "private"))
    user_id = str(current_user.id)
    dept_id_set = {str(dept_id) for _, dept_id in dept_pairs}

    if visibility == "private":
        if role == "department_admin":
            return bool(row.dept_id and str(row.dept_id) in dept_id_set)
        return str(row.created_by) == user_id
    if getattr(row, "public_scope", None) == "organization":
        return bool(row.org_id and row.org_id in org_ids)
    if getattr(row, "public_scope", None) == "department":
        dept_candidates = set(row.public_dept_ids or [])
        if row.dept_id:
            dept_candidates.add(str(row.dept_id))
        return bool(dept_candidates.intersection(dept_id_set))
    return False


def _connector_dept_candidates(row: ConnectorCatalogue) -> set[str]:
    dept_candidates = set(row.public_dept_ids or [])
    if row.dept_id:
        dept_candidates.add(str(row.dept_id))
    return dept_candidates


def _is_multi_dept_connector(row: ConnectorCatalogue) -> bool:
    return (
        _normalize_visibility(getattr(row, "visibility", "private")) == "public"
        and getattr(row, "public_scope", None) == "department"
        and len(_connector_dept_candidates(row)) > 1
    )


def _can_edit_connector(
    row: ConnectorCatalogue,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return (
            str(getattr(row, "created_by", "")) == str(current_user.id)
            and row.org_id is None
            and row.dept_id is None
        )

    role = normalize_role(str(current_user.role))
    if role == "super_admin":
        if (
            _normalize_visibility(getattr(row, "visibility", "private")) == "private"
            and row.org_id is None
            and row.dept_id is None
        ):
            return str(getattr(row, "created_by", "")) == str(current_user.id)
        return bool(row.org_id and row.org_id in org_ids)

    if role == "department_admin":
        if _is_multi_dept_connector(row):
            return False
        if _normalize_visibility(getattr(row, "visibility", "private")) == "public" and getattr(row, "public_scope", None) == "organization":
            return False
        dept_ids = {str(dept_id) for _, dept_id in dept_pairs}
        dept_candidates = _connector_dept_candidates(row)
        if _normalize_visibility(getattr(row, "visibility", "private")) == "private":
            return bool(dept_candidates.intersection(dept_ids))
        if getattr(row, "public_scope", None) == "department":
            return bool(dept_candidates.intersection(dept_ids))
        return False

    if role in {"developer", "business_user"}:
        return (
            _normalize_visibility(getattr(row, "visibility", "private")) == "private"
            and str(getattr(row, "created_by", "")) == str(current_user.id)
        )

    return False


def _can_delete_connector(
    row: ConnectorCatalogue,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return (
            str(getattr(row, "created_by", "")) == str(current_user.id)
            and row.org_id is None
            and row.dept_id is None
        )

    role = normalize_role(str(current_user.role))
    user_id = str(current_user.id)

    if role == "super_admin":
        if (
            _normalize_visibility(getattr(row, "visibility", "private")) == "private"
            and row.org_id is None
            and row.dept_id is None
        ):
            return str(getattr(row, "created_by", "")) == user_id
        return bool(row.org_id and row.org_id in org_ids)

    if role == "department_admin":
        if _is_multi_dept_connector(row):
            return False
        if _normalize_visibility(getattr(row, "visibility", "private")) == "public" and getattr(row, "public_scope", None) == "organization":
            return False
        dept_ids = {str(dept_id) for _, dept_id in dept_pairs}
        dept_candidates = _connector_dept_candidates(row)
        if _normalize_visibility(getattr(row, "visibility", "private")) == "private":
            return bool(dept_candidates.intersection(dept_ids))
        if getattr(row, "public_scope", None) == "department":
            return bool(dept_candidates.intersection(dept_ids))
        return False

    if role in {"developer", "business_user"}:
        return _normalize_visibility(getattr(row, "visibility", "private")) == "private" and str(getattr(row, "created_by", "")) == user_id

    return False


def _test_connector_payload_or_raise(payload: TestConnectionPayload) -> dict:
    provider = (payload.provider or "").strip().lower()
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")

    if provider in STORAGE_PROVIDERS:
        config = payload.provider_config or {}
        if provider == "azure_blob":
            return _test_azure_blob_connection(config)
        return _test_sharepoint_connection(config)

    if provider in EMAIL_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail="Outlook connectors must be saved first and linked via OAuth before they can be tested.",
        )

    if not payload.host or not payload.port or not payload.database_name or not payload.username:
        raise HTTPException(
            status_code=400,
            detail="host, port, database_name, username are required for DB providers",
        )
    return _test_db_connection(
        provider=provider,
        host=payload.host,
        port=payload.port,
        database_name=payload.database_name,
        schema_name=payload.schema_name or "public",
        username=payload.username,
        password=payload.password or "",
        ssl_enabled=bool(payload.ssl_enabled),
    )


# ---------- DB Connection helper ----------

def _test_db_connection(provider: str, host: str, port: int, database_name: str,
                        schema_name: str, username: str, password: str,
                        ssl_enabled: bool) -> dict:
    """Test a database connection and optionally fetch schema metadata."""
    start = time.time()

    if provider == "postgresql":
        import psycopg2
        conn_params = {
            "host": host,
            "port": port,
            "dbname": database_name,
            "user": username,
            "password": password,
            "connect_timeout": 10,
        }
        if ssl_enabled:
            conn_params["sslmode"] = "require"

        conn = psycopg2.connect(**conn_params)
        cur = conn.cursor()
        cur.execute("SELECT 1")

        # Fetch table/column metadata
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name NOT LIKE 'pg_%%'
              AND table_name NOT LIKE 'sql_%%'
            ORDER BY table_name, ordinal_position
        """, (schema_name,))
        columns = cur.fetchall()

        tables = {}
        for tbl, col, dtype, nullable, default in columns:
            if tbl not in tables:
                tables[tbl] = {"table_name": tbl, "columns": []}
            tables[tbl]["columns"].append({
                "name": col,
                "type": dtype,
                "nullable": nullable == "YES",
            })

        # Get row counts
        for tbl in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{schema_name}"."{tbl}"')
                tables[tbl]["row_count"] = cur.fetchone()[0]
            except Exception:
                tables[tbl]["row_count"] = None

        cur.close()
        conn.close()
        latency_ms = round((time.time() - start) * 1000, 2)

        return {
            "success": True,
            "message": f"Connected successfully. Found {len(tables)} tables.",
            "latency_ms": latency_ms,
            "tables_metadata": list(tables.values()),
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' is not yet supported. Supported: postgresql",
        )


def _test_azure_blob_connection(config: dict) -> dict:
    """Test an Azure Blob Storage connection."""
    start = time.time()
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        raise HTTPException(
            status_code=400,
            detail=(
                "azure-storage-blob and azure-identity packages are required. "
                "Install with: pip install azure-storage-blob azure-identity"
            ),
        )

    account_url = config.get("account_url", "")
    container_name = config.get("container_name", "")
    prefix = config.get("blob_prefix", "")

    if not account_url:
        raise HTTPException(status_code=400, detail="account_url is required for Azure Blob connector")
    if not container_name:
        raise HTTPException(status_code=400, detail="container_name is required for Azure Blob connector")
    if config.get("connection_string") or config.get("connection_string_secret_name"):
        raise HTTPException(
            status_code=400,
            detail="connection_string is no longer supported for Azure Blob connector. Use account_url + container_name.",
        )

    credential = DefaultAzureCredential(
        exclude_environment_credential=True,
        exclude_interactive_browser_credential=True,
    )
    client = BlobServiceClient(account_url=account_url, credential=credential)
    try:
        container_client = client.get_container_client(container_name)
        container_client.get_container_properties()
        sample_blob = next(iter(container_client.list_blobs(name_starts_with=prefix or None)), None)
        latency_ms = round((time.time() - start) * 1000, 2)
    finally:
        close_client = getattr(client, "close", None)
        if callable(close_client):
            close_client()
        close_credential = getattr(credential, "close", None)
        if callable(close_credential):
            close_credential()

    return {
        "success": True,
        "message": (
            f"Connected successfully to container '{container_name}' via managed identity. "
            f"{'Found at least one blob.' if sample_blob else 'Container is accessible (no blobs found for the selected prefix).'}"
        ),
        "latency_ms": latency_ms,
        "tables_metadata": None,
    }


def _test_sharepoint_connection(config: dict) -> dict:
    """Test a SharePoint connection."""
    start = time.time()

    site_url = config.get("site_url", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")
    tenant_id = config.get("tenant_id", "")

    if not site_url or not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="site_url, client_id, and client_secret are required for SharePoint connector",
        )

    # Primary: test via Microsoft Graph API (same auth path the connector uses)
    if tenant_id:
        try:
            import httpx
            from urllib.parse import urlparse

            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = httpx.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            }, timeout=10)
            if token_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Azure AD token request failed ({token_resp.status_code}): {token_resp.text[:300]}",
                )
            access_token = token_resp.json()["access_token"]

            parsed = urlparse(site_url)
            hostname = parsed.hostname
            site_path = parsed.path.rstrip("/")
            if site_path and site_path != "/":
                graph_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
            else:
                graph_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/"

            headers = {"Authorization": f"Bearer {access_token}"}
            site_resp = httpx.get(graph_url, headers=headers, timeout=10)
            if site_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"SharePoint site resolution failed ({site_resp.status_code}): {site_resp.text[:300]}",
                )
            site_data = site_resp.json()
            site_id = site_data["id"]
            site_name = site_data.get("displayName", site_url)

            drives_resp = httpx.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
                headers=headers, timeout=10,
            )
            if drives_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"SharePoint drives listing failed ({drives_resp.status_code}): {drives_resp.text[:300]}",
                )

            latency_ms = round((time.time() - start) * 1000, 2)
            drive_count = len(drives_resp.json().get("value", []))
            # Decode the JWT roles claim to surface the *granted* Application
            # permissions. Previously Test Connection only proved read access
            # (token + drive list), so a user could see "connected" while
            # writes were silently impossible. Now we report write
            # capability honestly based on the JWT roles.
            from agentcore.services.permissions import (
                has_any_scope as _has_any,
                parse_jwt_roles as _parse_roles,
            )
            from agentcore.services.sharepoint.graph_sharepoint import (
                SHAREPOINT_WRITE_SCOPES as _WRITE_SCOPES,
            )
            roles = _parse_roles(access_token)
            can_write = _has_any(roles or None, _WRITE_SCOPES) if roles else None
            write_note = (
                " Write access verified (Sites.ReadWrite.All / Files.ReadWrite.All / Sites.Selected)."
                if can_write
                else (
                    " Read-only: app registration lacks Sites.ReadWrite.All. "
                    "Uploads and folder creation will return 403."
                    if can_write is False
                    else " Write capability unknown (no roles in token)."
                )
            )
            return {
                "success": True,
                "message": (
                    f"Connected successfully to SharePoint site: {site_name} "
                    f"({drive_count} document libraries found)." + write_note
                ),
                "latency_ms": latency_ms,
                "granted_roles": roles,
                "can_write": can_write,
                "tables_metadata": None,
            }
        except HTTPException:
            raise
        except Exception as graph_err:
            logger.warning(f"Graph API test failed, falling back to Office365 library: {graph_err}")

    # Fallback: test via Office365-REST-Python-Client (legacy SharePoint REST API)
    try:
        from office365.runtime.auth.client_credential import ClientCredential
        from office365.sharepoint.client_context import ClientContext
    except ImportError:
        raise HTTPException(
            status_code=400,
            detail="Office365-REST-Python-Client not installed. Install with: pip install Office365-REST-Python-Client",
        )

    credentials = ClientCredential(client_id, client_secret)
    ctx = ClientContext(site_url).with_credentials(credentials)
    web = ctx.web
    ctx.load(web)
    ctx.execute_query()

    latency_ms = round((time.time() - start) * 1000, 2)
    return {
        "success": True,
        "message": f"Connected successfully to SharePoint site: {web.url}",
        "latency_ms": latency_ms,
        "tables_metadata": None,
    }


async def _test_outlook_connection(config: dict) -> dict:
    """Test an Outlook connection by calling Microsoft Graph /me endpoint.

    Attempts a token refresh if the stored access_token is expired and a
    refresh_token is available.  When a refresh occurs the *config* dict is
    mutated in-place so the caller can persist the updated tokens.

    Returns dict with ``_tokens_refreshed: True`` when tokens were updated.
    """
    import httpx

    start = time.time()
    tokens_refreshed = False

    linked_accounts = config.get("linked_accounts", [])
    if not linked_accounts:
        raise HTTPException(
            status_code=400,
            detail="No linked mailbox accounts. Use the OAuth flow to link a mailbox first.",
        )

    acct = linked_accounts[0]
    access_token = acct.get("access_token", "")
    account_email = acct.get("email", "unknown")

    if not access_token:
        raise HTTPException(
            status_code=400,
            detail=f"No access token for account '{account_email}'. Re-link the mailbox via OAuth.",
        )

    # If token looks expired, try to refresh before testing
    expires_at = acct.get("token_expires_at", 0)
    if expires_at and time.time() >= (expires_at - 60):
        refresh_token = acct.get("refresh_token", "")
        tenant_id = config.get("tenant_id", "")
        client_id = config.get("client_id", "")
        client_secret = config.get("client_secret", "")
        if refresh_token and tenant_id and client_id and client_secret:
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            # Use ``.default`` so reduced-permission app registrations (e.g.
            # Mail.Read only) don't get rejected with AADSTS65001 during the
            # Test Connection refresh. The granted scope set is whatever
            # admin-consented for the app, not the full hardcoded list.
            async with httpx.AsyncClient(timeout=15) as client:
                refresh_resp = await client.post(token_url, data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "https://graph.microsoft.com/.default offline_access",
                })
            if refresh_resp.status_code == 200:
                token_data = refresh_resp.json()
                access_token = token_data["access_token"]
                # Persist refreshed tokens back into config so caller can save
                acct["access_token"] = access_token
                acct["refresh_token"] = token_data.get("refresh_token", refresh_token)
                acct["token_expires_at"] = time.time() + token_data.get("expires_in", 3600)
                tokens_refreshed = True

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    latency_ms = round((time.time() - start) * 1000, 2)

    if resp.status_code != 200:
        detail = resp.text[:300] if resp.text else str(resp.status_code)
        raise HTTPException(
            status_code=400,
            detail=f"Microsoft Graph /me returned {resp.status_code}: {detail}",
        )

    data = resp.json()
    display = data.get("displayName") or data.get("userPrincipalName") or "unknown"
    return {
        "success": True,
        "message": f"Authenticated as {display} ({account_email})",
        "latency_ms": latency_ms,
        "tables_metadata": None,
        "_tokens_refreshed": tokens_refreshed,
    }


# ---------- Endpoints ----------

@router.get("")
@router.get("/")
async def list_connectors(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    await _require_connector_permission(current_user, "view_connector_page")
    query = select(ConnectorCatalogue).order_by(ConnectorCatalogue.name.asc())
    rows = (await session.exec(query)).all()
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    visible_rows = [row for row in rows if _can_access_connector(row, current_user, org_ids, dept_pairs)]
    creator_ids = [row.created_by for row in visible_rows if row.created_by]
    created_by_lookup: dict[str, dict[str, str | None]] = {}
    if creator_ids:
        creator_rows = (
            await session.exec(
                select(User.id, User.display_name, User.email, User.username).where(User.id.in_(creator_ids))
            )
        ).all()
        created_by_lookup = {
            str(row[0]): {
                "display": _creator_display_name(row[1], row[2], row[3]) or str(row[0]),
                "email": _creator_email(row[2], row[3]),
            }
            for row in creator_rows
        }
    return [_serialize_connector(row, created_by_lookup) for row in visible_rows]


@router.get("/visibility-options")
async def get_connector_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_connector_permission(current_user, "view_connector_page")
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


@router.post("")
@router.post("/")
async def create_connector(
    payload: ConnectorPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_connector_permission(current_user, "view_connector_page")
    await _require_connector_permission(current_user, "add_connector")

    provider = payload.provider.lower()
    if provider not in EMAIL_PROVIDERS:
        draft_payload = (
            TestConnectionPayload(provider=provider, provider_config=payload.provider_config or {})
            if provider in STORAGE_PROVIDERS
            else TestConnectionPayload(
                provider=provider,
                host=payload.host,
                port=payload.port,
                database_name=payload.database_name,
                schema_name=payload.schema_name,
                username=payload.username,
                password=payload.password,
                ssl_enabled=payload.ssl_enabled,
            )
        )
        test_result = _test_connector_payload_or_raise(draft_payload)
        if not test_result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=test_result.get("message") or "Connector connection test failed",
            )

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(
        session, current_user, payload
    )
    await _ensure_connector_name_available(session, payload.name, payload.org_id, payload.dept_id)
    now = datetime.now(timezone.utc)

    connector_id = uuid4()

    if provider in STORAGE_PROVIDERS | EMAIL_PROVIDERS:
        # Azure Blob / SharePoint / Outlook: credentials go into provider_config, not DB fields
        raw_config = payload.provider_config or {}
        _ensure_provider_secret_present(provider, raw_config)
        prepared_config = _prepare_provider_config(
            provider,
            raw_config,
            connector_id=connector_id,
        )
        row = ConnectorCatalogue(
            id=connector_id,
            name=payload.name,
            description=payload.description,
            provider=provider,
            host=None,
            port=None,
            database_name=None,
            schema_name=None,
            username=None,
            password_secret_name=None,
            ssl_enabled=False,
            provider_config=prepared_config,
            status="disconnected",
            is_custom=payload.is_custom,
            org_id=payload.org_id,
            dept_id=payload.dept_id,
            visibility=visibility,
            public_scope=public_scope,
            public_dept_ids=public_dept_ids,
            shared_user_ids=shared_user_ids,
            created_by=current_user.id,
            updated_by=current_user.id,
            created_at=now,
            updated_at=now,
        )
    else:
        # DB providers: use standard DB fields
        if not payload.password:
            raise HTTPException(status_code=400, detail="password is required for database connectors")
        password_secret_name = _build_secret_name(
            _secret_prefix(),
            connector_id,
            provider,
            "password",
        )
        _store_secret_value(password_secret_name, payload.password)

        row = ConnectorCatalogue(
            id=connector_id,
            name=payload.name,
            description=payload.description,
            provider=provider,
            host=payload.host,
            port=payload.port,
            database_name=payload.database_name,
            schema_name=payload.schema_name,
            username=payload.username,
            password_secret_name=password_secret_name,
            ssl_enabled=payload.ssl_enabled,
            provider_config=None,
            status="disconnected",
            is_custom=payload.is_custom,
            org_id=payload.org_id,
            dept_id=payload.dept_id,
            visibility=visibility,
            public_scope=public_scope,
            public_dept_ids=public_dept_ids,
            shared_user_ids=shared_user_ids,
            created_by=current_user.id,
            updated_by=current_user.id,
            created_at=now,
            updated_at=now,
        )

    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize_connector(row)


@router.patch("/{connector_id}")
async def update_connector(
    connector_id: UUID,
    payload: ConnectorUpdatePayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_connector_permission(current_user, "view_connector_page")
    await _require_connector_permission(current_user, "add_connector")

    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_edit_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Not authorized to edit this connector")

    if payload.org_id is None:
        payload.org_id = row.org_id
    if payload.dept_id is None and payload.public_scope != "organization":
        payload.dept_id = row.dept_id
    if payload.visibility is None:
        payload.visibility = row.visibility
    if payload.public_scope is None:
        payload.public_scope = row.public_scope
    if payload.public_dept_ids is None:
        payload.public_dept_ids = [UUID(v) for v in (row.public_dept_ids or [])]

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(
        session, current_user, payload
    )
    if payload.name is not None:
        await _ensure_connector_name_available(
            session,
            payload.name,
            payload.org_id,
            payload.dept_id,
            exclude_id=connector_id,
        )
    now = datetime.now(timezone.utc)

    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.provider is not None:
        row.provider = payload.provider.lower()

    effective_provider = row.provider

    if effective_provider in STORAGE_PROVIDERS | EMAIL_PROVIDERS:
        # Storage / Email provider: update provider_config, clear DB fields
        if payload.provider_config is not None:
            if effective_provider in EMAIL_PROVIDERS and row.provider_config:
                # Preserve linked_accounts/tokens when editing Outlook connectors
                existing = dict(row.provider_config or {})
                merged = {**existing, **payload.provider_config}
                # Don't let an empty client_secret overwrite the stored one
                if not payload.provider_config.get("client_secret") and existing.get("client_secret_secret_name"):
                    merged["client_secret_secret_name"] = existing["client_secret_secret_name"]
                for guard_key in ("linked_accounts", "access_token", "refresh_token", "token_expires_at"):
                    if not merged.get(guard_key) and existing.get(guard_key):
                        merged[guard_key] = existing[guard_key]
                _ensure_provider_secret_present(effective_provider, merged, existing)
                row.provider_config = _prepare_provider_config(
                    effective_provider,
                    merged,
                    connector_id=row.id,
                    existing_config=existing,
                )
            else:
                _ensure_provider_secret_present(
                    effective_provider,
                    payload.provider_config,
                    row.provider_config or {},
                )
                row.provider_config = _prepare_provider_config(
                    effective_provider,
                    payload.provider_config,
                    connector_id=row.id,
                    existing_config=row.provider_config or {},
                )
        elif not row.provider_config:
            _ensure_provider_secret_present(effective_provider, {}, {})
        row.host = None
        row.port = None
        row.database_name = None
        row.schema_name = None
        row.username = None
        row.password_secret_name = None
        row.ssl_enabled = False
    else:
        # DB provider: update DB fields
        if payload.host is not None:
            row.host = payload.host
        if payload.port is not None:
            row.port = payload.port
        if payload.database_name is not None:
            row.database_name = payload.database_name
        if payload.schema_name is not None:
            row.schema_name = payload.schema_name
        if payload.username is not None:
            row.username = payload.username
        if payload.password is not None:
            secret_name = _build_secret_name(
                _secret_prefix(),
                row.id,
                effective_provider,
                "password",
            )
            _store_secret_value(secret_name, payload.password)
            row.password_secret_name = secret_name
        elif not row.password_secret_name:
            raise HTTPException(status_code=400, detail="password is required for database connectors")
        if payload.ssl_enabled is not None:
            row.ssl_enabled = payload.ssl_enabled
        row.provider_config = None

    if payload.is_custom is not None:
        row.is_custom = payload.is_custom
    row.org_id = payload.org_id
    row.dept_id = payload.dept_id
    row.visibility = visibility
    row.public_scope = public_scope
    row.public_dept_ids = public_dept_ids
    row.shared_user_ids = shared_user_ids or []
    if visibility == "private":
        row.created_by = current_user.id
    row.updated_by = current_user.id
    row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return _serialize_connector(row)


@router.delete("/{connector_id}")
async def delete_connector(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_connector_permission(current_user, "view_connector_page")
    await _require_connector_permission(current_user, "add_connector")

    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_delete_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Not authorized to delete this connector")

    await session.delete(row)
    await session.commit()
    return {"message": "Connector deleted successfully"}


@router.post("/{connector_id}/test-connection")
async def test_connector_connection(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    override: TestConnectionPayload | None = None,
) -> dict:
    """Test connectivity to the configured database and refresh schema metadata."""
    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    await _require_connector_permission(current_user, "view_connector_page")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Connector is outside your visibility scope")

    provider = override.provider if override and override.provider else row.provider

    try:
        if provider in STORAGE_PROVIDERS:
            # Use provider_config (override or stored, decrypted)
            if override and override.provider_config:
                config = _decrypt_provider_config(provider, override.provider_config)
            else:
                config = _decrypt_provider_config(provider, row.provider_config or {})

            if provider == "azure_blob":
                result = _test_azure_blob_connection(config)
            else:  # sharepoint
                result = _test_sharepoint_connection(config)
        elif provider in EMAIL_PROVIDERS:
            config = _decrypt_provider_config(provider, row.provider_config or {})
            if override and override.provider_config:
                # Merge override fields but preserve linked_accounts from stored config
                linked = config.get("linked_accounts", [])
                config.update(override.provider_config)
                if linked and "linked_accounts" not in override.provider_config:
                    config["linked_accounts"] = linked
            result = await _test_outlook_connection(config)
        else:
            # DB provider
            host = override.host if override and override.host else row.host
            port = override.port if override and override.port else row.port
            database_name = override.database_name if override and override.database_name else row.database_name
            schema_name = override.schema_name if override and override.schema_name else row.schema_name
            username = override.username if override and override.username else row.username
            password = (
                override.password if override and override.password
                else (_resolve_secret_value(row.password_secret_name) if row.password_secret_name else "")
            )
            ssl_enabled = override.ssl_enabled if override and override.ssl_enabled is not None else row.ssl_enabled
            result = _test_db_connection(provider, host, port, database_name, schema_name, username, password, ssl_enabled)

        # If Outlook tokens were refreshed during the test, persist them
        if result.get("_tokens_refreshed") and provider in EMAIL_PROVIDERS:
            row.provider_config = _prepare_provider_config(
                provider,
                config,
                connector_id=row.id,
                existing_config=row.provider_config or {},
                allow_secret_update=False,
            )
            result.pop("_tokens_refreshed", None)

        now = datetime.now(timezone.utc)
        row.status = "connected"
        row.tables_metadata = result.get("tables_metadata")
        row.last_tested_at = now
        row.updated_at = now
        await session.commit()
        await session.refresh(row)
        return result
    except HTTPException:
        raise
    except Exception as e:
        now = datetime.now(timezone.utc)
        row.status = "error"
        row.last_tested_at = now
        row.updated_at = now
        await session.commit()
        return {
            "success": False,
            "message": f"Connection failed: {e!s}",
            "latency_ms": None,
            "tables_metadata": None,
        }


@router.post("/test-connection")
async def test_connector_connection_payload(
    payload: TestConnectionPayload,
    current_user: CurrentActiveUser,
) -> dict:
    """Test connectivity from unsaved connector payload (used by create modal)."""
    await _require_connector_permission(current_user, "view_connector_page")
    await _require_connector_permission(current_user, "add_connector")

    try:
        return _test_connector_payload_or_raise(payload)
    except HTTPException:
        raise
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection failed: {e!s}",
            "latency_ms": None,
            "tables_metadata": None,
        }


@router.post("/{connector_id}/disconnect")
async def disconnect_connector(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Manually disconnect a connector (set status to 'disconnected')."""
    await _require_connector_permission(current_user, "view_connector_page")
    await _require_connector_permission(current_user, "add_connector")

    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Connector is outside your visibility scope")

    now = datetime.now(timezone.utc)
    row.status = "disconnected"
    row.updated_at = now
    row.updated_by = current_user.id
    await session.commit()
    await session.refresh(row)
    return {"message": "Connector disconnected", "status": "disconnected"}


@router.get("/{connector_id}/schema")
async def get_connector_schema(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Return cached schema metadata for a connector."""
    await _require_connector_permission(current_user, "view_connector_page")
    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Connector is outside your visibility scope")

    return {
        "connector_id": str(row.id),
        "connector_name": row.name,
        "provider": row.provider,
        "database_name": row.database_name,
        "schema_name": row.schema_name,
        "status": row.status,
        "tables_metadata": row.tables_metadata or [],
        "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
    }
