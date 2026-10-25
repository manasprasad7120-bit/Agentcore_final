"""sync MCP registry permissions with page and API contract

Revision ID: mcp20260319001
Revises: ds20260319002
Create Date: 2026-03-19
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "mcp20260319001"
down_revision: str | Sequence[str] | None = "ds20260319002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "edit_mcp_registry": "MCP Servers",
    "delete_mcp_registry": "MCP Servers",
}

DEFAULT_ROLE_GRANTS = {
    "root": {"add_new_mcp", "edit_mcp_registry", "delete_mcp_registry"},
    "super_admin": {"add_new_mcp", "edit_mcp_registry", "delete_mcp_registry"},
    "department_admin": {"add_new_mcp", "edit_mcp_registry", "delete_mcp_registry"},
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _permission_id_by_key(bind) -> dict[str, str]:
    rows = bind.execute(sa.text("SELECT id, key FROM permission")).fetchall()
    return {str(row[1]): str(row[0]) for row in rows}


def _role_id_by_name(bind) -> dict[str, str]:
    rows = bind.execute(sa.text("SELECT id, name FROM role")).fetchall()
    return {str(row[1]): str(row[0]) for row in rows}


def _upsert_permission(bind, key: str, category: str) -> None:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    existing = bind.execute(sa.text("SELECT id FROM permission WHERE key = :key"), {"key": key}).fetchone()
    if existing:
        set_parts = ["name = :name", "description = :description"]
        params = {"key": key, "name": key, "description": category}
        if has_category:
            set_parts.append("category = :category")
            params["category"] = category
        if has_is_system:
            set_parts.append("is_system = :is_system")
            params["is_system"] = True
        if has_updated_at:
            set_parts.append("updated_at = now()")
        bind.execute(sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"), params)
        return

    cols = ["id", "key", "name", "description"]
    vals = [":id", ":key", ":name", ":description"]
    params = {"id": str(uuid4()), "key": key, "name": key, "description": category}
    if has_category:
        cols.append("category")
        vals.append(":category")
        params["category"] = category
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


def upgrade() -> None:
    bind = op.get_bind()
    if not all(_table_exists(bind, table) for table in ("permission", "role", "role_permission")):
        return

    for key, category in PERMISSIONS.items():
        _upsert_permission(bind, key, category)

    permission_ids = _permission_id_by_key(bind)
    role_ids = _role_id_by_name(bind)

    retire_perm_id = permission_ids.get("retire_mcp")
    delete_perm_id = permission_ids.get("delete_mcp_registry")
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")

    if retire_perm_id and delete_perm_id:
        role_rows = bind.execute(
            sa.text("SELECT DISTINCT role_id FROM role_permission WHERE permission_id = :permission_id"),
            {"permission_id": retire_perm_id},
        ).fetchall()
        role_ids_with_retire = [str(row[0]) for row in role_rows]
        for role_id in role_ids_with_retire:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permission (id, role_id, permission_id{created_at_col}{updated_at_col})
                    SELECT :id, :role_id, :permission_id{created_at_val}{updated_at_val}
                    WHERE NOT EXISTS (
                        SELECT 1 FROM role_permission
                        WHERE role_id = :role_id AND permission_id = :permission_id
                    )
                    """.format(
                        created_at_col=", created_at" if has_created_at else "",
                        updated_at_col=", updated_at" if has_updated_at else "",
                        created_at_val=", now()" if has_created_at else "",
                        updated_at_val=", now()" if has_updated_at else "",
                    )
                ),
                {"id": str(uuid4()), "role_id": role_id, "permission_id": delete_perm_id},
            )
        bind.execute(
            sa.text("DELETE FROM role_permission WHERE permission_id = :permission_id"),
            {"permission_id": retire_perm_id},
        )

    for role_name, permission_keys in DEFAULT_ROLE_GRANTS.items():
        role_id = role_ids.get(role_name)
        if not role_id:
            continue
        for permission_key in permission_keys:
            permission_id = permission_ids.get(permission_key)
            if not permission_id:
                continue
            insert_cols = ["id", "role_id", "permission_id"]
            insert_vals = [":id", ":role_id", ":permission_id"]
            params = {"id": str(uuid4()), "role_id": role_id, "permission_id": permission_id}
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


def downgrade() -> None:
    # Keep permissions/grants to avoid regressing live RBAC.
    return
