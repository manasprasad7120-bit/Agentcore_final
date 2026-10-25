"""rename permission keys to new canonical names

Revision ID: s1t2u3v4w5x6
Revises: rb1a2b3c4d5
Create Date: 2026-03-19
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "s1t2u3v4w5x6"
down_revision: str | Sequence[str] | None = "rb1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSION_RENAMES: dict[str, list[str]] = {
    "edit_project": ["edit_projects_page"],
    "view_registry_agent": ["view_only_agent"],
    "edit_model": ["edit_model_registry"],
    "delete_model": ["delete_model_registry"],
    "view_connector_page": ["connectore_page", "view_connectors_page", "connector_page"],
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _get_permission_rows(bind, keys: list[str]) -> list[sa.Row]:
    return list(
        bind.execute(
            sa.text(
                """
                SELECT id, key, name, description, category, is_system, created_by, created_at, updated_by, updated_at
                FROM permission
                WHERE key = ANY(:keys)
                """
            ),
            {"keys": keys},
        ).mappings()
    )


def _ensure_permission(bind, key: str, source_row: sa.Row | None) -> str:
    existing = bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": key},
    ).scalar()
    if existing:
        return str(existing)

    now = datetime.now(timezone.utc)
    permission_id = str(uuid4())
    bind.execute(
        sa.text(
            """
            INSERT INTO permission (
                id, key, name, description, category, is_system,
                created_by, created_at, updated_by, updated_at
            ) VALUES (
                :id, :key, :name, :description, :category, :is_system,
                :created_by, :created_at, :updated_by, :updated_at
            )
            """
        ),
        {
            "id": permission_id,
            "key": key,
            "name": source_row["name"] if source_row else key.replace("_", " "),
            "description": source_row["description"] if source_row else None,
            "category": source_row["category"] if source_row else None,
            "is_system": source_row["is_system"] if source_row else True,
            "created_by": source_row["created_by"] if source_row else None,
            "created_at": source_row["created_at"] if source_row else now,
            "updated_by": source_row["updated_by"] if source_row else None,
            "updated_at": now,
        },
    )
    return permission_id


def _remap_permission(bind, new_key: str, old_keys: list[str]) -> None:
    rows = _get_permission_rows(bind, [new_key, *old_keys])
    if not rows:
        return

    new_row = next((row for row in rows if row["key"] == new_key), None)
    old_rows = [row for row in rows if row["key"] in old_keys]
    target_permission_id = _ensure_permission(bind, new_key, new_row or (old_rows[0] if old_rows else None))

    for old_row in old_rows:
        old_permission_id = str(old_row["id"])
        bind.execute(
            sa.text(
                """
                DELETE FROM role_permission rp
                USING role_permission existing_rp
                WHERE rp.permission_id = :old_permission_id
                  AND existing_rp.permission_id = :target_permission_id
                  AND rp.role_id = existing_rp.role_id
                """
            ),
            {
                "old_permission_id": old_permission_id,
                "target_permission_id": target_permission_id,
            },
        )
        bind.execute(
            sa.text(
                """
                UPDATE role_permission
                SET permission_id = :target_permission_id,
                    updated_at = :updated_at
                WHERE permission_id = :old_permission_id
                """
            ),
            {
                "target_permission_id": target_permission_id,
                "old_permission_id": old_permission_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        bind.execute(
            sa.text("DELETE FROM permission WHERE id = :old_permission_id"),
            {"old_permission_id": old_permission_id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    if not (_table_exists(bind, "permission") and _table_exists(bind, "role_permission")):
        return

    for new_key, old_keys in PERMISSION_RENAMES.items():
        _remap_permission(bind, new_key, old_keys)


def downgrade() -> None:
    bind = op.get_bind()
    if not (_table_exists(bind, "permission") and _table_exists(bind, "role_permission")):
        return

    downgrade_pairs = {
        "edit_project": "edit_projects_page",
        "view_registry_agent": "view_only_agent",
        "edit_model": "edit_model_registry",
        "delete_model": "delete_model_registry",
        "view_connector_page": "connectore_page",
    }

    for current_key, old_key in downgrade_pairs.items():
        rows = _get_permission_rows(bind, [current_key, old_key])
        if not rows:
            continue

        current_row = next((row for row in rows if row["key"] == current_key), None)
        old_row = next((row for row in rows if row["key"] == old_key), None)
        if not current_row:
            continue

        target_permission_id = _ensure_permission(bind, old_key, old_row or current_row)
        current_permission_id = str(current_row["id"])

        bind.execute(
            sa.text(
                """
                DELETE FROM role_permission rp
                USING role_permission existing_rp
                WHERE rp.permission_id = :current_permission_id
                  AND existing_rp.permission_id = :target_permission_id
                  AND rp.role_id = existing_rp.role_id
                """
            ),
            {
                "current_permission_id": current_permission_id,
                "target_permission_id": target_permission_id,
            },
        )
        bind.execute(
            sa.text(
                """
                UPDATE role_permission
                SET permission_id = :target_permission_id,
                    updated_at = :updated_at
                WHERE permission_id = :current_permission_id
                """
            ),
            {
                "target_permission_id": target_permission_id,
                "current_permission_id": current_permission_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if not old_row:
            bind.execute(
                sa.text("DELETE FROM permission WHERE id = :current_permission_id"),
                {"current_permission_id": current_permission_id},
            )
