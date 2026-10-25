"""add leader executive system role and move dashboard access from root

Revision ID: le1a2d3e4r5
Revises: mcp20260319002
Create Date: 2026-03-19
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "le1a2d3e4r5"
down_revision: str | Sequence[str] | None = "mcp20260319002"
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


def _ensure_leader_role(bind) -> str | None:
    role_id = _get_role_id(bind, "leader_executive")
    now = datetime.now(timezone.utc)

    if role_id:
        if _has_column(bind, "role", "display_name") and _has_column(bind, "role", "description"):
            bind.execute(
                sa.text(
                    """
                    UPDATE role
                    SET display_name = :display_name,
                        description = :description,
                        is_system = true,
                        is_active = true,
                        updated_at = :updated_at
                    WHERE id = :role_id
                    """
                ),
                {
                    "role_id": role_id,
                    "display_name": "Leader/Executive",
                    "description": "Executive dashboard role with dashboard-only access.",
                    "updated_at": now,
                },
            )
        return role_id

    role_id = str(uuid4())
    cols = ["id", "name", "display_name", "description", "is_system", "is_active"]
    vals = [":id", ":name", ":display_name", ":description", "true", "true"]
    params: dict[str, object] = {
        "id": role_id,
        "name": "leader_executive",
        "display_name": "Leader/Executive",
        "description": "Executive dashboard role with dashboard-only access.",
    }

    if _has_column(bind, "role", "created_at"):
        cols.append("created_at")
        vals.append(":created_at")
        params["created_at"] = now
    if _has_column(bind, "role", "updated_at"):
        cols.append("updated_at")
        vals.append(":updated_at")
        params["updated_at"] = now
    if _has_column(bind, "role", "created_by"):
        cols.append("created_by")
        vals.append("NULL")
    if _has_column(bind, "role", "updated_by"):
        cols.append("updated_by")
        vals.append("NULL")

    bind.execute(
        sa.text(
            f"INSERT INTO role ({', '.join(cols)}) VALUES ({', '.join(vals)})"
        ),
        params,
    )
    return role_id


def _delete_role_permission(bind, role_id: str, permission_id: str) -> None:
    bind.execute(
        sa.text(
            "DELETE FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": role_id, "permission_id": permission_id},
    )


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

    leader_role_id = _ensure_leader_role(bind)
    root_role_id = _get_role_id(bind, "root")
    dashboard_permission_id = _get_permission_id(bind, "view_dashboard")

    if not leader_role_id or not dashboard_permission_id:
        return

    bind.execute(
        sa.text("DELETE FROM role_permission WHERE role_id = :role_id"),
        {"role_id": leader_role_id},
    )
    _ensure_role_permission(bind, leader_role_id, dashboard_permission_id)

    if root_role_id:
        _ensure_role_permission(bind, root_role_id, dashboard_permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    if not all(_table_exists(bind, table) for table in ("role", "permission", "role_permission")):
        return

    leader_role_id = _get_role_id(bind, "leader_executive")
    root_role_id = _get_role_id(bind, "root")
    dashboard_permission_id = _get_permission_id(bind, "view_dashboard")

    if leader_role_id:
        bind.execute(
            sa.text("DELETE FROM role_permission WHERE role_id = :role_id"),
            {"role_id": leader_role_id},
        )
        bind.execute(
            sa.text("DELETE FROM role WHERE id = :role_id"),
            {"role_id": leader_role_id},
        )

    if root_role_id and dashboard_permission_id:
        _ensure_role_permission(bind, root_role_id, dashboard_permission_id)
