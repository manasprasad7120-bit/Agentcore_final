from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alembic.util.exc import CommandError
from loguru import logger
from sqlmodel import select, text
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from agentcore.services.database.service import DatabaseService


async def initialize_database(*, fix_migration: bool = False) -> None:
    logger.debug("Initializing database")
    from agentcore.services.deps import get_db_service

    database_service: DatabaseService = get_db_service()
    try:
        if database_service.settings_service.settings.database_connection_retry:
            await database_service.create_db_and_tables_with_retry()
        else:
            await database_service.create_db_and_tables()
    except Exception as exc:
        # if the exception involves tables already existing
        # we can ignore it
        if "already exists" not in str(exc):
            msg = "Error creating DB and tables"
            logger.exception(msg)
            raise RuntimeError(msg) from exc
    try:
        await database_service.check_schema_health()
    except Exception as exc:
        msg = "Error checking schema health"
        logger.exception(msg)
        raise RuntimeError(msg) from exc
    try:
        await database_service.run_migrations(fix=fix_migration)
    except CommandError as exc:
        # if "overlaps with other requested revisions" or "Can't locate revision identified by"
        # are not in the exception, we can't handle it
        if "overlaps with other requested revisions" not in str(
            exc
        ) and "Can't locate revision identified by" not in str(exc):
            raise
        # This means there's wrong revision in the DB
        # We need to delete the alembic_version table
        # and run the migrations again
        logger.warning("Wrong revision in DB, deleting alembic_version table and running migrations again")
        async with session_getter(database_service) as session:
            await session.exec(text("DROP TABLE alembic_version"))
        await database_service.run_migrations(fix=fix_migration)
    except Exception as exc:
        # if the exception involves tables already existing
        # we can ignore it
        if "already exists" not in str(exc):
            logger.exception(exc)
        raise
    try:
        await _seed_predefined_tags(database_service)
    except Exception:
        logger.exception("Failed to seed predefined tags (non-fatal)")
    logger.debug("Database initialized")


async def _seed_predefined_tags(db_service: DatabaseService) -> None:
    """Insert predefined tags if they don't already exist."""
    from agentcore.services.database.models.tag.model import PREDEFINED_TAGS, Tag

    async with session_getter(db_service) as session:
        for tag_def in PREDEFINED_TAGS:
            existing = (
                await session.exec(
                    select(Tag).where(Tag.name == tag_def["name"], Tag.is_predefined.is_(True))
                )
            ).first()
            if not existing:
                session.add(
                    Tag(
                        name=tag_def["name"],
                        category=tag_def["category"],
                        description=tag_def["description"],
                        is_predefined=True,
                        org_id=None,
                        created_by=None,
                    )
                )
        await session.commit()
    logger.debug("Predefined tags seeded")


@asynccontextmanager
async def session_getter(db_service: DatabaseService):
    try:
        session = AsyncSession(db_service.engine, expire_on_commit=False)
        yield session
    except Exception:
        logger.exception("Session rollback because of exception")
        await session.rollback()
        raise
    finally:
        await session.close()


@dataclass
class Result:
    name: str
    type: str
    success: bool


@dataclass
class TableResults:
    table_name: str
    results: list[Result]
