"""Add MCP action permissions (edit/delete).

Revision ID: c1d2e3f4g5h6
Revises: b7c8d9e0f1a2
Create Date: 2026-03-16
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c1d2e3f4g5h6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("edit_mcp_registry", "MCP Servers"),
    ("delete_mcp_registry", "MCP Servers"),
]

ROLE_GRANTS = {
    "root": ["edit_mcp_registry", "delete_mcp_registry"],
    "super_admin": ["edit_mcp_registry", "delete_mcp_registry"],
    "department_admin": ["edit_mcp_registry", "delete_mcp_registry"],
}


def _table_exists(bind, name: str) -> bool:
    row = bind.execute(sa.text("SELECT to_regclass(:name)"), {"name": name}).fetchone()
    return bool(row and row[0])


def _has_column(bind, table: str, column: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table, "col": column},
    ).fetchone()
    return bool(row)


def _is_uuid_column(bind, table: str, column: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table, "col": column},
    ).fetchone()
    return bool(row and str(row[0]).lower() == "uuid")


def _upsert_permission(bind, key: str, category: str) -> None:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    row = bind.execute(sa.text("SELECT id FROM permission WHERE key = :key"), {"key": key}).fetchone()
    if row:
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
    if not (_table_exists(op.get_bind(), "permission") and _table_exists(op.get_bind(), "role") and _table_exists(op.get_bind(), "role_permission")):
        return

    bind = op.get_bind()
    for key, category in PERMISSIONS:
        _upsert_permission(bind, key, category)

    role_rows = bind.execute(sa.text("SELECT id, name FROM role")).fetchall()
    role_id_by_name = {str(r[1]): str(r[0]) for r in role_rows}

    permission_rows = bind.execute(
        sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": [k for keys in ROLE_GRANTS.values() for k in keys]},
    ).fetchall()
    permission_id_by_key = {str(r[1]): str(r[0]) for r in permission_rows}

    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")
    has_created_by = _has_column(bind, "role_permission", "created_by")
    has_updated_by = _has_column(bind, "role_permission", "updated_by")
    created_by_is_uuid = _is_uuid_column(bind, "role_permission", "created_by") if has_created_by else False
    updated_by_is_uuid = _is_uuid_column(bind, "role_permission", "updated_by") if has_updated_by else False

    for role_name, keys in ROLE_GRANTS.items():
        role_id = role_id_by_name.get(role_name)
        if not role_id:
            continue
        for key in keys:
            permission_id = permission_id_by_key.get(key)
            if not permission_id:
                continue
            insert_cols = ["id", "role_id", "permission_id"]
            insert_vals = [":id", ":role_id", ":permission_id"]
            params = {"id": str(uuid4()), "role_id": role_id, "permission_id": permission_id}
            if has_created_by and not created_by_is_uuid:
                insert_cols.append("created_by")
                insert_vals.append(":created_by")
                params["created_by"] = "system"
            if has_updated_by and not updated_by_is_uuid:
                insert_cols.append("updated_by")
                insert_vals.append(":updated_by")
                params["updated_by"] = "system"
            if has_created_at:
                insert_cols.append("created_at")
                insert_vals.append("now()")
            if has_updated_at:
                insert_cols.append("updated_at")
                insert_vals.append("now()")

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


def downgrade() -> None:
    # Keep permissions; non-destructive downgrade.
    return
