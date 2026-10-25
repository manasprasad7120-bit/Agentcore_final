"""restore root dashboard permission after leader executive rollout

Revision ID: le1a2d3e4r6
Revises: le1a2d3e4r5
Create Date: 2026-03-19
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "le1a2d3e4r6"
down_revision: str | Sequence[str] | None = "le1a2d3e4r5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def _get_role_id(bind, role_name: str) -> str | None:
    return bind.execute(
        sa.text("SELECT id FROM role WHERE name = :name"),
        {"name": role_name},
    ).scalar()


def _get_permission_id(bind, permission_key: str) -> str | None:
    return bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": permission_key},
    ).scalar()


def _ensure_role_permission(bind, role_id: str, permission_id: str) -> None:
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")
    has_created_by = _has_column(bind, "role_permission", "created_by")
    has_updated_by = _has_column(bind, "role_permission", "updated_by")
    now = datetime.now(timezone.utc)

    cols = ["id", "role_id", "permission_id"]
    vals = [":id", ":role_id", ":permission_id"]
    params: dict[str, object] = {
        "id": str(uuid4()),
        "role_id": role_id,
        "permission_id": permission_id,
    }
    if has_created_at:
        cols.append("created_at")
        vals.append(":created_at")
        params["created_at"] = now
    if has_updated_at:
        cols.append("updated_at")
        vals.append(":updated_at")
        params["updated_at"] = now
    if has_created_by:
        cols.append("created_by")
        vals.append("NULL")
    if has_updated_by:
        cols.append("updated_by")
        vals.append("NULL")

    bind.execute(
        sa.text(
            f"""
            INSERT INTO role_permission ({', '.join(cols)})
            SELECT {', '.join(vals)}
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permission
                WHERE role_id = :role_id AND permission_id = :permission_id
            )
            """
        ),
        params,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not all(_table_exists(bind, table) for table in ("role", "permission", "role_permission")):
        return

    root_role_id = _get_role_id(bind, "root")
    dashboard_permission_id = _get_permission_id(bind, "view_dashboard")
    if not root_role_id or not dashboard_permission_id:
        return

    _ensure_role_permission(bind, root_role_id, dashboard_permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "role_permission"):
        return

    root_role_id = _get_role_id(bind, "root")
    dashboard_permission_id = _get_permission_id(bind, "view_dashboard")
    if not root_role_id or not dashboard_permission_id:
        return

    bind.execute(
        sa.text(
            "DELETE FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": root_role_id, "permission_id": dashboard_permission_id},
    )
