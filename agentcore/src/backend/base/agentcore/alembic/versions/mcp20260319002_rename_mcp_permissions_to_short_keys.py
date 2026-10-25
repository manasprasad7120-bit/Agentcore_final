"""rename MCP permissions to short canonical keys

Revision ID: mcp20260319002
Revises: mcp20260319001
Create Date: 2026-03-19
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "mcp20260319002"
down_revision: str | Sequence[str] | None = "mcp20260319001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSION_CATEGORY = "MCP"
KEY_RENAMES = {
    "edit_mcp_registry": "edit_mcp",
    "delete_mcp_registry": "delete_mcp",
    "retire_mcp": "delete_mcp",
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _permission_rows(bind) -> dict[str, tuple[str, str]]:
    rows = bind.execute(sa.text("SELECT id, key FROM permission")).fetchall()
    return {str(row[1]): (str(row[0]), str(row[1])) for row in rows}


def _upsert_permission(bind, key: str) -> str:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    existing = bind.execute(sa.text("SELECT id FROM permission WHERE key = :key"), {"key": key}).fetchone()
    if existing:
        params = {"key": key, "name": key, "description": PERMISSION_CATEGORY}
        set_parts = ["name = :name", "description = :description"]
        if has_category:
            set_parts.append("category = :category")
            params["category"] = PERMISSION_CATEGORY
        if has_is_system:
            set_parts.append("is_system = :is_system")
            params["is_system"] = True
        if has_updated_at:
            set_parts.append("updated_at = now()")
        bind.execute(sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"), params)
        return str(existing[0])

    cols = ["id", "key", "name", "description"]
    vals = [":id", ":key", ":name", ":description"]
    params = {"id": str(uuid4()), "key": key, "name": key, "description": PERMISSION_CATEGORY}
    if has_category:
        cols.append("category")
        vals.append(":category")
        params["category"] = PERMISSION_CATEGORY
    if has_is_system:
        cols.append("is_system")
        vals.append(":is_system")
        params["is_system"] = True
    if has_created_at:
        cols.append("created_at")
        vals.append("now()")
    if has_updated_at:
        cols.append("updated_at")
        vals.append("now()")
    bind.execute(
        sa.text(f"INSERT INTO permission ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
        params,
    )
    return params["id"]


def _copy_role_permission_rows(bind, source_permission_id: str, target_permission_id: str) -> None:
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")

    role_rows = bind.execute(
        sa.text("SELECT DISTINCT role_id FROM role_permission WHERE permission_id = :permission_id"),
        {"permission_id": source_permission_id},
    ).fetchall()
    for row in role_rows:
        role_id = str(row[0])
        params = {"id": str(uuid4()), "role_id": role_id, "permission_id": target_permission_id}
        insert_cols = ["id", "role_id", "permission_id"]
        insert_vals = [":id", ":role_id", ":permission_id"]
        if has_created_at:
            insert_cols.append("created_at")
            insert_vals.append("now()")
        if has_updated_at:
            insert_cols.append("updated_at")
            insert_vals.append("now()")
        bind.execute(
            sa.text(
                f"""
                INSERT INTO role_permission ({', '.join(insert_cols)})
                SELECT {', '.join(insert_vals)}
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
    if not all(_table_exists(bind, table) for table in ("permission", "role_permission")):
        return

    edit_id = _upsert_permission(bind, "edit_mcp")
    delete_id = _upsert_permission(bind, "delete_mcp")

    permission_rows = _permission_rows(bind)
    for old_key, new_key in KEY_RENAMES.items():
        row = permission_rows.get(old_key)
        if not row:
            continue
        source_id = row[0]
        target_id = edit_id if new_key == "edit_mcp" else delete_id
        if source_id != target_id:
            _copy_role_permission_rows(bind, source_id, target_id)
            bind.execute(
                sa.text("DELETE FROM role_permission WHERE permission_id = :permission_id"),
                {"permission_id": source_id},
            )
            bind.execute(
                sa.text("DELETE FROM permission WHERE id = :permission_id"),
                {"permission_id": source_id},
            )

    # Normalize surviving canonical rows
    bind.execute(
        sa.text(
            "UPDATE permission SET key = :key, name = :name, description = :description WHERE id = :permission_id"
        ),
        {"key": "edit_mcp", "name": "edit_mcp", "description": PERMISSION_CATEGORY, "permission_id": edit_id},
    )
    bind.execute(
        sa.text(
            "UPDATE permission SET key = :key, name = :name, description = :description WHERE id = :permission_id"
        ),
        {"key": "delete_mcp", "name": "delete_mcp", "description": PERMISSION_CATEGORY, "permission_id": delete_id},
    )


def downgrade() -> None:
    return
