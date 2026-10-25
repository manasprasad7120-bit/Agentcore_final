"""fix agent registry permission after view_agent collision

Revision ID: s2u3v4w5x6y7
Revises: s1t2u3v4w5x6
Create Date: 2026-03-19
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "s2u3v4w5x6y7"
down_revision: str | Sequence[str] | None = "s1t2u3v4w5x6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_ROLES_WITH_AGENT_REGISTRY_VIEW = [
    "root",
    "super_admin",
    "department_admin",
    "developer",
    "business_user",
    "consumer",
]


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _ensure_permission(bind, key: str, *, name: str, category: str) -> str:
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
                id, key, name, category, is_system,
                created_at, updated_at
            ) VALUES (
                :id, :key, :name, :category, :is_system,
                :created_at, :updated_at
            )
            """
        ),
        {
            "id": permission_id,
            "key": key,
            "name": name,
            "category": category,
            "is_system": True,
            "created_at": now,
            "updated_at": now,
        },
    )
    return permission_id


def upgrade() -> None:
    bind = op.get_bind()
    if not (_table_exists(bind, "permission") and _table_exists(bind, "role") and _table_exists(bind, "role_permission")):
        return

    permission_id = _ensure_permission(
        bind,
        "view_registry_agent",
        name="view registry agent",
        category="Agent Registry",
    )

    role_rows = bind.execute(
        sa.text("SELECT id, name FROM role WHERE name = ANY(:role_names)"),
        {"role_names": SYSTEM_ROLES_WITH_AGENT_REGISTRY_VIEW},
    ).mappings()

    now = datetime.now(timezone.utc)
    for row in role_rows:
        role_id = str(row["id"])
        exists = bind.execute(
            sa.text(
                """
                SELECT 1
                FROM role_permission
                WHERE role_id = :role_id AND permission_id = :permission_id
                """
            ),
            {"role_id": role_id, "permission_id": permission_id},
        ).scalar()
        if exists:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permission (id, role_id, permission_id, created_at, updated_at)
                VALUES (:id, :role_id, :permission_id, :created_at, :updated_at)
                """
            ),
            {
                "id": str(uuid4()),
                "role_id": role_id,
                "permission_id": permission_id,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not (_table_exists(bind, "permission") and _table_exists(bind, "role_permission")):
        return

    permission_id = bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": "view_registry_agent"},
    ).scalar()
    if not permission_id:
        return

    bind.execute(
        sa.text("DELETE FROM role_permission WHERE permission_id = :permission_id"),
        {"permission_id": str(permission_id)},
    )
    bind.execute(
        sa.text("DELETE FROM permission WHERE id = :permission_id"),
        {"permission_id": str(permission_id)},
    )
