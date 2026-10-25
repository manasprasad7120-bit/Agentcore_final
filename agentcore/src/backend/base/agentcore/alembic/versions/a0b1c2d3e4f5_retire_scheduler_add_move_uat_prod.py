"""retire add_scheduler and add move_uat_to_prod permission

Revision ID: a0b1c2d3e4f5
Revises: z9y8x7w6v5u4
Create Date: 2026-03-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "z9y8x7w6v5u4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_PERMISSION = ("move_uat_to_prod", "Agent Control Panel")
DEFAULT_ROLES = ["root", "super_admin", "department_admin", "developer", "business_user"]
RETIRED_PERMISSION = "add_scheduler"
MIGRATE_TO_PERMISSION = "start_stop_agent"


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _get_permission_id(bind, key: str):
    row = bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": key},
    ).fetchone()
    return row[0] if row else None


def _is_uuid_column(bind, table_name: str, column_name: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :table_name AND column_name = :column_name"
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchone()
    return bool(row and str(row[0]).lower() == "uuid")


def _upsert_permission(bind, key: str, category: str) -> None:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    existing = _get_permission_id(bind, key)
    params = {
        "key": key,
        "name": key.replace("_", " "),
        "description": None,
        "category": category,
        "is_system": True,
    }

    if existing:
        set_parts = ["name = :name", "description = :description"]
        if has_category:
            set_parts.append("category = :category")
        if has_is_system:
            set_parts.append("is_system = :is_system")
        if has_updated_at:
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
        bind.execute(
            sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"),
            params,
        )
        return

    insert_cols = ["id", "key", "name", "description"]
    insert_vals = [":id", ":key", ":name", ":description"]
    params["id"] = str(uuid4())
    if has_category:
        insert_cols.append("category")
        insert_vals.append(":category")
    if has_is_system:
        insert_cols.append("is_system")
        insert_vals.append(":is_system")
    if has_created_at:
        insert_cols.append("created_at")
        insert_vals.append("CURRENT_TIMESTAMP")
    if has_updated_at:
        insert_cols.append("updated_at")
        insert_vals.append("CURRENT_TIMESTAMP")

    bind.execute(
        sa.text(
            f"INSERT INTO permission ({', '.join(insert_cols)}) VALUES ({', '.join(insert_vals)})"
        ),
        params,
    )


def _role_id_by_name(bind, role_name: str):
    row = bind.execute(
        sa.text("SELECT id FROM role WHERE name = :name"),
        {"name": role_name},
    ).fetchone()
    return row[0] if row else None


def _ensure_role_permission(bind, role_id, permission_id) -> None:
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")
    has_created_by = _has_column(bind, "role_permission", "created_by")
    has_updated_by = _has_column(bind, "role_permission", "updated_by")
    created_by_is_uuid = _is_uuid_column(bind, "role_permission", "created_by") if has_created_by else False
    updated_by_is_uuid = _is_uuid_column(bind, "role_permission", "updated_by") if has_updated_by else False
    now = datetime.now(timezone.utc)

    insert_cols = ["id", "role_id", "permission_id"]
    insert_vals = [":id", ":role_id", ":permission_id"]
    params: dict[str, object] = {
        "id": str(uuid4()),
        "role_id": role_id,
        "permission_id": permission_id,
    }

    if has_created_by:
        insert_cols.append("created_by")
        if created_by_is_uuid:
            insert_vals.append("NULL")
        else:
            insert_vals.append(":created_by")
            params["created_by"] = "system"

    if has_updated_by:
        insert_cols.append("updated_by")
        if updated_by_is_uuid:
            insert_vals.append("NULL")
        else:
            insert_vals.append(":updated_by")
            params["updated_by"] = "system"

    if has_created_at:
        insert_cols.append("created_at")
        insert_vals.append(":created_at")
        params["created_at"] = now

    if has_updated_at:
        insert_cols.append("updated_at")
        insert_vals.append(":updated_at")
        params["updated_at"] = now

    bind.execute(
        sa.text(
            f"INSERT INTO role_permission ({', '.join(insert_cols)}) "
            f"SELECT {', '.join(insert_vals)} "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
            ")"
        ),
        params,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission") or not _table_exists(bind, "role_permission"):
        return

    _upsert_permission(bind, NEW_PERMISSION[0], NEW_PERMISSION[1])
    move_perm_id = _get_permission_id(bind, NEW_PERMISSION[0])
    start_stop_perm_id = _get_permission_id(bind, MIGRATE_TO_PERMISSION)
    retired_perm_id = _get_permission_id(bind, RETIRED_PERMISSION)

    if retired_perm_id and start_stop_perm_id:
        rows = bind.execute(
            sa.text("SELECT DISTINCT role_id FROM role_permission WHERE permission_id = :permission_id"),
            {"permission_id": retired_perm_id},
        ).fetchall()
        for row in rows:
            _ensure_role_permission(bind, row[0], start_stop_perm_id)

    if move_perm_id:
        for role_name in DEFAULT_ROLES:
            role_id = _role_id_by_name(bind, role_name)
            if role_id:
                _ensure_role_permission(bind, role_id, move_perm_id)

    if retired_perm_id:
        bind.execute(
            sa.text("DELETE FROM role_permission WHERE permission_id = :permission_id"),
            {"permission_id": retired_perm_id},
        )
        bind.execute(
            sa.text("DELETE FROM permission WHERE id = :permission_id"),
            {"permission_id": retired_perm_id},
        )


def downgrade() -> None:
    return
