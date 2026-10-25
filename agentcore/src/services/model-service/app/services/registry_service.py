"""CRUD operations for the model registry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID

from cachetools import TTLCache
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.registry import (
    ModelRegistry,
    ModelRegistryCreate,
    ModelRegistryRead,
    ModelRegistryUpdate,
)
from app.utils.key_vault import KeyVaultConfig, KeyVaultSecretStore, model_api_key_secret_name
from app.utils.local_secrets import LocalEncryptedSecretStore

logger = logging.getLogger(__name__)


# Hot-path cache for the rate-limit lookup. The registry row is read on every
# inference call to enforce limits, but RPM/TPM rarely change, so a short-TTL
# in-process cache absorbs the load. Invalidated on update_model / delete_model
# so a UI edit takes effect immediately on the replica that served the edit;
# other replicas pick up the change within the TTL.
_RATE_LIMIT_CACHE: TTLCache[UUID, tuple[int | None, int | None]] | None = None


def _get_rate_limit_cache() -> TTLCache[UUID, tuple[int | None, int | None]]:
    global _RATE_LIMIT_CACHE  # noqa: PLW0603
    if _RATE_LIMIT_CACHE is None:
        settings = get_settings()
        _RATE_LIMIT_CACHE = TTLCache(
            maxsize=settings.rate_limit_cache_size,
            ttl=settings.rate_limit_cache_ttl_seconds,
        )
    return _RATE_LIMIT_CACHE


def _invalidate_rate_limit_cache(model_id: UUID) -> None:
    cache = _get_rate_limit_cache()
    cache.pop(model_id, None)

API_KEY_REQUIRED_PROVIDERS = {
    "openai",
    "azure",
    "azure_openai",
    "openai_compatible",
    "groq",
    "anthropic",
    "google",
}


@lru_cache(maxsize=1)
def _build_key_vault_store() -> KeyVaultSecretStore | LocalEncryptedSecretStore | None:
    settings = get_settings()
    config = KeyVaultConfig(
        vault_url=settings.key_vault_url,
        secret_prefix=settings.key_vault_secret_prefix,
    )
    store = KeyVaultSecretStore.from_config(config)
    if store is None:
        # No Azure Key Vault configured: keep provider API keys in the local
        # Fernet-encrypted store instead (local demos / deployments without Azure).
        local_store = LocalEncryptedSecretStore(encryption_key=settings.encryption_key)
        logger.warning(
            "MODEL_SERVICE_KEY_VAULT_URL is not set; provider API keys are stored in the local "
            "encrypted secret store at %s",
            local_store.path,
        )
        return local_store
    return store


def _get_secret_name(row: ModelRegistry) -> str | None:
    return row.api_key_secret_ref


def _require_key_vault_store() -> KeyVaultSecretStore | LocalEncryptedSecretStore:
    key_vault = _build_key_vault_store()
    if key_vault is None:
        msg = (
            "Azure Key Vault is required for model registry secrets. "
            "Set MODEL_SERVICE_KEY_VAULT_URL."
        )
        raise RuntimeError(msg)
    return key_vault


async def create_model(
    session: AsyncSession,
    data: ModelRegistryCreate,
) -> ModelRegistryRead:
    """Insert a new model into the registry."""
    settings = get_settings()
    key_vault = _require_key_vault_store()
    provider = (data.provider or "").strip().lower()

    if provider in API_KEY_REQUIRED_PROVIDERS and not data.api_key:
        raise HTTPException(status_code=400, detail="API key is required for this provider.")

    row = ModelRegistry(
        display_name=data.display_name,
        description=data.description,
        provider=data.provider,
        model_name=data.model_name,
        model_type=data.model_type,
        base_url=data.base_url,
        environment=data.environment,
        provider_config=data.provider_config,
        capabilities=data.capabilities,
        default_params=data.default_params,
        show_in=data.show_in,
        is_active=data.is_active,
        created_by=data.created_by,
        rate_limit_rpm=data.rate_limit_rpm,
        rate_limit_tpm=data.rate_limit_tpm,
        # Tenancy / RBAC fields
        org_id=data.org_id,
        dept_id=data.dept_id,
        public_dept_ids=data.public_dept_ids,
        created_by_id=data.created_by_id,
        visibility_scope=data.visibility_scope,
        approval_status=data.approval_status,
        requested_by=data.requested_by,
        request_to=data.request_to,
    )

    provider_config = dict(data.provider_config or {})
    row.provider_config = provider_config
    session.add(row)

    if data.api_key:
        await session.flush()
        secret_name = model_api_key_secret_name(
            settings.key_vault_secret_prefix,
            row.id,
            model_type=data.model_type,
            provider=data.provider,
        )
        await asyncio.to_thread(
            key_vault.set_secret,
            secret_name,
            data.api_key,
            tags={"service": "model-service", "type": "provider-api-key"},
        )
        row.provider_config = {
            **provider_config,
            "api_key_source": getattr(key_vault, "source_label", "azure_key_vault"),
        }
        row.api_key_secret_ref = secret_name

    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


async def get_models(
    session: AsyncSession,
    *,
    provider: str | None = None,
    environment: str | None = None,
    model_type: str | None = None,
    active_only: bool = True,
) -> list[ModelRegistryRead]:
    """Return all registry entries, optionally filtered."""
    stmt = select(ModelRegistry)
    if active_only:
        stmt = stmt.where(ModelRegistry.is_active.is_(True))
    if provider:
        stmt = stmt.where(ModelRegistry.provider == provider)
    if environment:
        stmt = stmt.where(ModelRegistry.environment == environment)
    if model_type:
        stmt = stmt.where(ModelRegistry.model_type == model_type)
    stmt = stmt.order_by(ModelRegistry.provider, ModelRegistry.display_name)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [ModelRegistryRead.from_orm_model(r) for r in rows]


async def get_model(session: AsyncSession, model_id: UUID) -> ModelRegistryRead | None:
    """Return a single registry entry by ID."""
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return None
    return ModelRegistryRead.from_orm_model(row)


async def update_model(
    session: AsyncSession,
    model_id: UUID,
    data: ModelRegistryUpdate,
) -> ModelRegistryRead | None:
    """Update an existing registry entry."""
    settings = get_settings()
    key_vault = _require_key_vault_store()

    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return None

    update_fields = data.model_dump(exclude_unset=True)

    # Handle API key separately
    plain_key = update_fields.pop("api_key", None)
    if (row.provider or "").strip().lower() in API_KEY_REQUIRED_PROVIDERS:
        if not plain_key and not row.api_key_secret_ref:
            raise HTTPException(status_code=400, detail="API key is required for this provider.")
    if plain_key:
        provider_config = dict(row.provider_config or {})
        secret_name = row.api_key_secret_ref or model_api_key_secret_name(
            settings.key_vault_secret_prefix,
            row.id,
            model_type=row.model_type,
            provider=row.provider,
        )
        await asyncio.to_thread(
            key_vault.set_secret,
            secret_name,
            plain_key,
            tags={"service": "model-service", "type": "provider-api-key"},
        )
        provider_config["api_key_source"] = getattr(key_vault, "source_label", "azure_key_vault")
        row.provider_config = provider_config
        row.api_key_secret_ref = secret_name

    for field, value in update_fields.items():
        setattr(row, field, value)

    row.updated_at = datetime.utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    _invalidate_rate_limit_cache(row.id)
    return ModelRegistryRead.from_orm_model(row)


async def delete_model(session: AsyncSession, model_id: UUID) -> bool:
    """Hard-delete a registry entry. Returns True if the row existed."""
    key_vault = _require_key_vault_store()
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return False
    secret_name = _get_secret_name(row)
    await session.delete(row)
    await session.commit()
    _invalidate_rate_limit_cache(model_id)
    if key_vault and secret_name:
        try:
            await asyncio.to_thread(key_vault.delete_secret, secret_name)
        except Exception:
            logger.warning("Failed to delete Key Vault secret '%s' for model %s", secret_name, model_id)
    return True


async def get_decrypted_config(
    session: AsyncSession,
    model_id: UUID,
) -> dict | None:
    """Return the full config with decrypted API key.  Internal use only (chat completions)."""
    key_vault = _require_key_vault_store()
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return None

    config: dict = {
        "provider": row.provider,
        "model_name": row.model_name,
        "model_type": row.model_type,
        "base_url": row.base_url,
        "environment": row.environment,
        "provider_config": row.provider_config or {},
        "capabilities": row.capabilities or {},
        "default_params": row.default_params or {},
    }

    secret_name = row.api_key_secret_ref

    if secret_name:
        secret_value = await asyncio.to_thread(key_vault.get_secret, secret_name)
        if not secret_value:
            msg = f"API key secret '{secret_name}' not found in Azure Key Vault for model {model_id}."
            raise RuntimeError(msg)
        config["api_key"] = secret_value
    else:
        config["api_key"] = ""

    return config


async def get_rate_limits(
    session: AsyncSession,
    model_id: UUID,
) -> tuple[int | None, int | None]:
    """Return ``(rate_limit_rpm, rate_limit_tpm)`` for a model.

    Cache-first; a miss reads the registry row and stores ``(rpm, tpm)`` for
    ``rate_limit_cache_ttl_seconds``. Returns ``(None, None)`` for an unknown
    model -- callers treat that as "unlimited" so a deleted/missing model
    doesn't block inference (the downstream config lookup will surface the
    real error).

    The values returned are normalized: 0 in the column is coerced to None to
    match the "0 means unlimited" contract documented on the schema.
    """
    cache = _get_rate_limit_cache()
    cached = cache.get(model_id)
    if cached is not None:
        return cached

    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return (None, None)

    rpm = row.rate_limit_rpm if row.rate_limit_rpm and row.rate_limit_rpm > 0 else None
    tpm = row.rate_limit_tpm if row.rate_limit_tpm and row.rate_limit_tpm > 0 else None
    cache[model_id] = (rpm, tpm)
    return (rpm, tpm)
