"""CRUD operations for the MCP server registry."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.database.models.mcp_registry.model import (
    McpRegistry,
    McpRegistryCreate,
    McpRegistryRead,
    McpRegistryUpdate,
)
from agentcore.utils.crypto import decrypt_api_key_with_fallback, derive_fernet_key, encrypt_api_key

from agentcore.services.settings.key_vault import KeyVaultConfig, KeyVaultSecretStore

logger = logging.getLogger(__name__)


_kv_store_cache: dict[str, KeyVaultSecretStore | None] = {}


def _encryption_key() -> str:
    """Return the primary encryption key from environment."""
    key = os.getenv("MODEL_REGISTRY_ENCRYPTION_KEY", "")
    if not key:
        raw = os.getenv("WEBUI_SECRET_KEY", "default-agentcore-registry-key")
        key = derive_fernet_key(raw)
    return key


def _encrypt_json(data: dict, enc_key: str) -> str:
    """Encrypt a dict as JSON string."""
    return encrypt_api_key(json.dumps(data), enc_key)


def _decrypt_json(encrypted: str, enc_key: str) -> dict:
    """Decrypt an encrypted JSON string back to dict."""
    return json.loads(decrypt_api_key_with_fallback(encrypted, enc_key))


def _is_fernet_token(value: str) -> bool:
    """Heuristic: Fernet tokens are base64-encoded and start with 'gAAAAA'."""
    return value.startswith("gAAAAA")


def _secret_prefix() -> str:
    prefix = os.getenv("AGENTCORE_KEY_VAULT_SECRET_PREFIX", "agentcore").strip()
    return prefix or "agentcore"


def _get_kv_store() -> KeyVaultSecretStore | None:
    vault_url = os.getenv("AGENTCORE_KEY_VAULT_URL", "").strip()
    if not vault_url:
        return None
    if vault_url in _kv_store_cache:
        return _kv_store_cache[vault_url]
    store = KeyVaultSecretStore.from_config(
        KeyVaultConfig(
            vault_url=vault_url,
            secret_prefix=_secret_prefix(),
        )
    )
    _kv_store_cache[vault_url] = store
    return store


def _build_secret_name(prefix: str, mcp_id: UUID, key: str) -> str:
    return f"{prefix}-mcp-{mcp_id}-{key}"


def _store_kv_json(name: str, value: dict) -> None:
    store = _get_kv_store()
    if store is None:
        return
    store.set_secret(name=name, value=json.dumps(value))


def _resolve_kv_json(secret_name: str) -> dict | None:
    store = _get_kv_store()
    if store is None:
        return None
    raw = store.get_secret(secret_name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Key Vault secret %s is not valid JSON", secret_name)
        return None


def apply_mcp_secret_refs(
    row: McpRegistry,
    *,
    env_vars: dict | None,
    headers: dict | None,
) -> None:
    """Persist env_vars/headers as secret refs (KV if configured, else Fernet)."""
    enc_key = _encryption_key()
    kv_store = _get_kv_store()
    prefix = _secret_prefix()

    if env_vars is not None:
        if not env_vars:
            row.env_vars_secret_ref = None
        elif kv_store is not None:
            existing = row.env_vars_secret_ref
            secret_name = (
                existing
                if existing and not _is_fernet_token(existing)
                else _build_secret_name(prefix, row.id, "env-vars")
            )
            _store_kv_json(secret_name, env_vars)
            row.env_vars_secret_ref = secret_name
        elif enc_key:
            row.env_vars_secret_ref = _encrypt_json(env_vars, enc_key)

    if headers is not None:
        if not headers:
            row.headers_secret_ref = None
        elif kv_store is not None:
            existing = row.headers_secret_ref
            secret_name = (
                existing
                if existing and not _is_fernet_token(existing)
                else _build_secret_name(prefix, row.id, "headers")
            )
            _store_kv_json(secret_name, headers)
            row.headers_secret_ref = secret_name
        elif enc_key:
            row.headers_secret_ref = _encrypt_json(headers, enc_key)


async def create_server(
    session: AsyncSession,
    data: McpRegistryCreate,
) -> McpRegistryRead:
    """Register a new MCP server."""
    enc_key = _encryption_key()
    row = McpRegistry(
        server_name=data.server_name,
        description=data.description,
        mode=data.mode,
        deployment_env=(data.deployment_env or "UAT").upper(),
        environments=data.environments,
        url=data.url,
        command=data.command,
        args=data.args,
        is_active=data.is_active,
        status=data.status,
        org_id=data.org_id,
        dept_id=data.dept_id,
        visibility=data.visibility,
        public_scope=data.public_scope,
        public_dept_ids=[str(v) for v in (data.public_dept_ids or [])] if data.public_dept_ids is not None else None,
        shared_user_ids=data.shared_user_ids,
        approval_status=data.approval_status,
        requested_by=data.requested_by,
        request_to=data.request_to,
        requested_at=data.requested_at,
        reviewed_at=data.reviewed_at,
        reviewed_by=data.reviewed_by,
        review_comments=data.review_comments,
        review_attachments=data.review_attachments,
        created_by=data.created_by,
        created_by_id=data.created_by_id,
    )

    apply_mcp_secret_refs(row, env_vars=data.env_vars, headers=data.headers)

    session.add(row)
    await session.commit()
    await session.refresh(row)
    return McpRegistryRead.from_orm_model(row)


async def get_servers(
    session: AsyncSession,
    *,
    active_only: bool = True,
) -> list[McpRegistryRead]:
    """Return all MCP servers, optionally filtered by active status."""
    stmt = select(McpRegistry)
    if active_only:
        stmt = stmt.where(McpRegistry.is_active.is_(True))
    stmt = stmt.order_by(McpRegistry.server_name)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [McpRegistryRead.from_orm_model(r) for r in rows]


async def get_server(session: AsyncSession, server_id: UUID) -> McpRegistryRead | None:
    """Return a single MCP server by ID."""
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return None
    return McpRegistryRead.from_orm_model(row)


async def get_server_by_name(session: AsyncSession, server_name: str) -> McpRegistryRead | None:
    """Return a single MCP server by name."""
    stmt = select(McpRegistry).where(McpRegistry.server_name == server_name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None
    return McpRegistryRead.from_orm_model(row)


async def update_server(
    session: AsyncSession,
    server_id: UUID,
    data: McpRegistryUpdate,
) -> McpRegistryRead | None:
    """Update an existing MCP server."""
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return None

    update_fields = data.model_dump(exclude_unset=True)
    if "public_dept_ids" in update_fields and update_fields["public_dept_ids"] is not None:
        update_fields["public_dept_ids"] = [str(v) for v in update_fields["public_dept_ids"]]
    if "deployment_env" in update_fields and update_fields["deployment_env"] is not None:
        update_fields["deployment_env"] = str(update_fields["deployment_env"]).upper()

    # Handle secrets separately
    plain_env_vars = update_fields.pop("env_vars", None)
    plain_headers = update_fields.pop("headers", None)
    if plain_env_vars is not None or plain_headers is not None:
        apply_mcp_secret_refs(row, env_vars=plain_env_vars, headers=plain_headers)

    for field, value in update_fields.items():
        setattr(row, field, value)

    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return McpRegistryRead.from_orm_model(row)


async def delete_server(session: AsyncSession, server_id: UUID) -> bool:
    """Hard-delete an MCP server. Returns True if the row existed."""
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def get_decrypted_config_by_id(
    session: AsyncSession,
    server_id: UUID,
) -> tuple[str, dict] | None:
    """Return (server_name, config_dict) with decrypted secrets, looked up by ID."""
    enc_key = _encryption_key()
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return None
    if not row.is_active or (row.approval_status or "approved") != "approved":
        return None

    config: dict = {}

    if row.mode == "sse":
        if row.url:
            config["url"] = row.url
        if row.headers_secret_ref:
            if _is_fernet_token(row.headers_secret_ref):
                config["headers"] = _decrypt_json(row.headers_secret_ref, enc_key)
            else:
                config["headers"] = _resolve_kv_json(row.headers_secret_ref) or {}
    elif row.mode == "stdio":
        if row.command:
            config["command"] = row.command
        if row.args:
            config["args"] = row.args

    if row.env_vars_secret_ref:
        if _is_fernet_token(row.env_vars_secret_ref):
            config["env"] = _decrypt_json(row.env_vars_secret_ref, enc_key)
        else:
            config["env"] = _resolve_kv_json(row.env_vars_secret_ref) or {}

    return row.server_name, config


async def get_decrypted_config(
    session: AsyncSession,
    server_name: str,
) -> dict | None:
    """Return the full MCP server config with decrypted secrets. Internal use only (components)."""
    enc_key = _encryption_key()
    stmt = select(McpRegistry).where(McpRegistry.server_name == server_name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None
    if not row.is_active or (row.approval_status or "approved") != "approved":
        return None

    config: dict = {}

    if row.mode == "sse":
        if row.url:
            config["url"] = row.url
        if row.headers_secret_ref:
            if _is_fernet_token(row.headers_secret_ref):
                config["headers"] = _decrypt_json(row.headers_secret_ref, enc_key)
            else:
                config["headers"] = _resolve_kv_json(row.headers_secret_ref) or {}
    elif row.mode == "stdio":
        if row.command:
            config["command"] = row.command
        if row.args:
            config["args"] = row.args

    # Env vars apply to both modes
    if row.env_vars_secret_ref:
        if _is_fernet_token(row.env_vars_secret_ref):
            config["env"] = _decrypt_json(row.env_vars_secret_ref, enc_key)
        else:
            config["env"] = _resolve_kv_json(row.env_vars_secret_ref) or {}

    return config
