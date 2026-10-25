from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
from loguru import logger
from sqlalchemy import delete
from sqlalchemy import exc as sqlalchemy_exc
from sqlmodel import col, select

from agentcore.services.cache.base import ExternalAsyncBaseCacheService
from agentcore.services.cache.factory import CacheServiceFactory
from agentcore.services.database.models.transactions.model import TransactionTable
from agentcore.services.database.models.vertex_builds.model import VertexBuildTable
from agentcore.services.database.utils import initialize_database
from agentcore.services.schema import ServiceType
from agentcore.services.auth import permissions
from agentcore.services.auth.permissions import PermissionCacheService
from agentcore.services.cache.user_cache import UserCacheService
from .deps import get_db_service, get_service, get_settings_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from agentcore.services.settings.manager import SettingsService


async def teardown_services() -> None:
    """Teardown all the services."""
    from agentcore.services.cache.redis_client import reset_redis_client
    from agentcore.services.manager import service_manager

    await service_manager.teardown()
    await reset_redis_client()


def initialize_settings_service() -> None:
    """Initialize the settings manager."""
    from agentcore.services.settings import factory as settings_factory

    get_service(ServiceType.SETTINGS_SERVICE, settings_factory.SettingsServiceFactory())


def initialize_session_service() -> None:
    """Initialize the session manager."""
    from agentcore.services.cache import factory as cache_factory
    from agentcore.services.session import factory as session_service_factory

    initialize_settings_service()

    get_service(
        ServiceType.CACHE_SERVICE,
        cache_factory.CacheServiceFactory(),
    )

    get_service(
        ServiceType.SESSION_SERVICE,
        session_service_factory.SessionServiceFactory(),
    )


async def clean_transactions(settings_service: SettingsService, session: AsyncSession) -> None:
    """Clean up old transactions from the database.

    This function deletes transactions that exceed the maximum number to keep (configured in settings).
    It orders transactions by timestamp descending and removes the oldest ones beyond the limit.

    Args:
        settings_service: The settings service containing configuration like max_transactions_to_keep
        session: The database session to use for the deletion
    """
    try:
        # Delete transactions using bulk delete
        delete_stmt = delete(TransactionTable).where(
            col(TransactionTable.id).in_(
                select(TransactionTable.id)
                .order_by(col(TransactionTable.timestamp).desc())
                .offset(settings_service.settings.max_transactions_to_keep)
            )
        )

        await session.exec(delete_stmt)
        await session.commit()
        logger.debug("Successfully cleaned up old transactions")
    except (sqlalchemy_exc.SQLAlchemyError, asyncio.TimeoutError) as exc:
        logger.error(f"Error cleaning up transactions: {exc!s}")
        await session.rollback()
        # Don't re-raise since this is a cleanup task


async def clean_vertex_builds(settings_service: SettingsService, session: AsyncSession) -> None:
    """Clean up old vertex builds from the database.

    This function deletes vertex builds that exceed the maximum number to keep (configured in settings).
    It orders vertex builds by timestamp descending and removes the oldest ones beyond the limit.

    Args:
        settings_service: The settings service containing configuration like max_vertex_builds_to_keep
        session: The database session to use for the deletion
    """
    try:
        # Delete vertex builds using bulk delete
        delete_stmt = delete(VertexBuildTable).where(
            col(VertexBuildTable.id).in_(
                select(VertexBuildTable.id)
                .order_by(col(VertexBuildTable.timestamp).desc())
                .offset(settings_service.settings.max_vertex_builds_to_keep)
            )
        )

        await session.exec(delete_stmt)
        await session.commit()
        logger.debug("Successfully cleaned up old vertex builds")
    except (sqlalchemy_exc.SQLAlchemyError, asyncio.TimeoutError) as exc:
        logger.error(f"Error cleaning up vertex builds: {exc!s}")
        await session.rollback()
        # Don't re-raise since this is a cleanup task


def _permission_category(key: str) -> str:
    if key.startswith("view_"):
        return "Pages"
    if key.startswith(("manage_", "assign_", "approve_")):
        return "Administration"
    return "Actions"


async def ensure_default_roles_and_permissions(session: AsyncSession) -> None:
    """Seed the system roles and permissions from ROLE_PERMISSIONS when the role table is empty.

    Fresh databases get their schema from the SQLModel metadata and Alembic is stamped to head,
    so the data-seeding migrations never run. Without this, every role except ``root`` would have
    no permissions. Databases that already contain roles are left untouched.
    """
    from agentcore.services.database.models.permission.model import Permission
    from agentcore.services.database.models.role.model import Role
    from agentcore.services.database.models.role_permission.model import RolePermission

    try:
        if (await session.exec(select(Role))).first() is not None:
            return

        role_map = permissions.ROLE_PERMISSIONS
        perm_keys = sorted({key for keys in role_map.values() for key in keys})
        perms_by_key = {perm.key: perm for perm in (await session.exec(select(Permission))).all()}
        for key in perm_keys:
            if key not in perms_by_key:
                perm = Permission(
                    key=key,
                    name=key.replace("_", " ").title(),
                    description=f"System permission '{key}' (seeded from defaults).",
                    category=_permission_category(key),
                    is_system=True,
                )
                session.add(perm)
                perms_by_key[key] = perm
        await session.flush()

        for role_name, keys in role_map.items():
            role = Role(
                name=role_name,
                display_name=role_name.replace("_", " ").title(),
                description=f"System role '{role_name}' (seeded from defaults).",
                is_system=True,
            )
            session.add(role)
            await session.flush()
            for key in dict.fromkeys(keys):
                session.add(RolePermission(role_id=role.id, permission_id=perms_by_key[key].id))

        await session.commit()
        logger.info(
            f"Seeded {len(role_map)} system roles and {len(perm_keys)} permissions from ROLE_PERMISSIONS defaults"
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to seed default roles/permissions (continuing startup)")
        await session.rollback()


async def ensure_local_superuser(session: AsyncSession) -> None:
    """Create or refresh a local root user from AGENTCORE_SUPERUSER / AGENTCORE_SUPERUSER_PASSWORD.

    No-op when either variable is unset. When set, the user is guaranteed to exist, be active,
    have the ``root`` role and the configured password, so the platform is usable without SSO.
    """
    username = (os.getenv("AGENTCORE_SUPERUSER") or "").strip()
    password = os.getenv("AGENTCORE_SUPERUSER_PASSWORD") or ""
    if not username or not password:
        return

    from agentcore.services.auth.utils import get_password_hash, verify_password
    from agentcore.services.database.models.user.crud import get_user_by_username
    from agentcore.services.database.models.user.model import User

    normalized = username.lower() if "@" in username else username
    try:
        user = await get_user_by_username(session, normalized)
        if user is None:
            user = User(
                username=normalized,
                email=normalized if "@" in normalized else None,
                display_name="Local Administrator",
                password=get_password_hash(password),
                role="root",
                is_superuser=True,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            logger.info(f"Local root user '{normalized}' created from AGENTCORE_SUPERUSER")
            return

        changed = False
        if not user.is_active or user.deleted_at is not None:
            user.is_active, user.deleted_at, changed = True, None, True
        if not user.is_superuser or permissions.normalize_role(user.role) != "root":
            user.is_superuser, user.role, changed = True, "root", True
        if not verify_password(password, user.password):
            user.password, changed = get_password_hash(password), True
        if changed:
            session.add(user)
            await session.commit()
            logger.info(f"Local root user '{normalized}' updated from AGENTCORE_SUPERUSER settings")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to bootstrap local superuser (continuing startup)")
        await session.rollback()


async def initialize_services(*, fix_migration: bool = False) -> None:
    """Initialize all the services needed."""
    settings_service = get_service(ServiceType.SETTINGS_SERVICE)
    cache_service = get_service(ServiceType.CACHE_SERVICE, default=CacheServiceFactory())
    # Test external cache connection and gracefully fall back for local/dev runs.
    if isinstance(cache_service, ExternalAsyncBaseCacheService) and not (await cache_service.is_connected()):
        strict_cache_startup = os.getenv("CACHE_STRICT_STARTUP", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if strict_cache_startup:
            msg = "Cache service failed to connect to external database"
            raise ConnectionError(msg)

        from agentcore.services.cache.service import AsyncInMemoryCache
        from agentcore.services.manager import service_manager

        fallback_ttl = settings_service.settings.cache_expire or settings_service.settings.redis_cache_expire or 3600
        fallback_cache_service = AsyncInMemoryCache(expiration_time=fallback_ttl)
        fallback_cache_service.set_ready()
        service_manager.services[ServiceType.CACHE_SERVICE] = fallback_cache_service
        settings_service.settings.cache_type = "async"
        cache_service = fallback_cache_service
        logger.warning(
            "Cache service failed to connect to external database. "
            "Falling back to in-memory async cache. "
            "Set CACHE_STRICT_STARTUP=false to allow fallback."
        )

    # Initialize database
    await initialize_database(fix_migration=fix_migration)
    db_service = get_db_service()
    await db_service.initialize_alembic_log_file()
    async with db_service.with_session() as session:
        # Users are normally provisioned via Azure Entra SSO. For environments without
        # Azure (local demos), a root user can be bootstrapped from AGENTCORE_SUPERUSER /
        # AGENTCORE_SUPERUSER_PASSWORD so username/password login works.
        await ensure_default_roles_and_permissions(session)
        await ensure_local_superuser(session)
        await clean_transactions(settings_service, session)
        await clean_vertex_builds(settings_service, session)
    try:
        permissions.permission_cache = PermissionCacheService(settings_service)
        _user_cache_service = UserCacheService(settings_service)  # Can store globally if needed
    except Exception as e:
        logger.warning(f"Failed to init auth cache: {e}")
        permissions.permission_cache = None
    logger.info("Auth cache services initialized")
