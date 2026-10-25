"""add model registry action permissions and backfill org_id

Revision ID: d0e1f2a3b4c5
Revises: 18d101d98961
Create Date: 2026-03-15
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "18d101d98961"
branch_labels = None
depends_on = None


PERMISSIONS: list[tuple[str, str]] = [
    ("edit_model_registry", "Model Registry"),
    ("delete_model_registry", "Model Registry"),
]

# Keep default roles aligned; Access Control can still override later.
DEFAULT_ROLE_PERMISSION_ADDITIONS: dict[str, list[str]] = {
    "root": ["edit_model_registry", "delete_model_registry"],
    "super_admin": ["edit_model_registry", "delete_model_registry"],
    "department_admin": ["edit_model_registry", "delete_model_registry"],
}


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _upsert_permission(bind, key: str, category: str) -> None:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    existing = bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": key},
    ).fetchone()

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
        bind.execute(sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"), params)
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
        sa.text(f"INSERT INTO permission ({', '.join(insert_cols)}) VALUES ({', '.join(insert_vals)})"),
        params,
    )


def _ensure_role_permission(bind, *, role_id: str, permission_id: str) -> None:
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")

    insert_cols = ["id", "role_id", "permission_id"]
    insert_vals = [":id", ":role_id", ":permission_id"]
    if has_created_at:
        insert_cols.append("created_at")
        insert_vals.append("CURRENT_TIMESTAMP")
    if has_updated_at:
        insert_cols.append("updated_at")
        insert_vals.append("CURRENT_TIMESTAMP")

    bind.execute(
        sa.text(
            f"INSERT INTO role_permission ({', '.join(insert_cols)}) "
            f"SELECT {', '.join(insert_vals)} "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
            ")"
        ),
        {"id": str(uuid4()), "role_id": role_id, "permission_id": permission_id},
    )


def _backfill_model_org_id(bind) -> None:
    if not _table_exists(bind, "model_registry"):
        return
    if not _has_column(bind, "model_registry", "org_id"):
        return
    if not _has_column(bind, "model_registry", "dept_id"):
        return

    # Prefer department.org_id when dept_id exists.
    if _table_exists(bind, "department") and _has_column(bind, "department", "org_id"):
        bind.execute(
            sa.text(
                "UPDATE model_registry m "
                "SET org_id = d.org_id "
                "FROM department d "
                "WHERE m.org_id IS NULL AND m.dept_id IS NOT NULL AND d.id = m.dept_id"
            )
        )

    # Best-effort: infer from creator organization membership.
    if _table_exists(bind, "user_organization_membership"):
        bind.execute(
            sa.text(
                "UPDATE model_registry m "
                "SET org_id = uom.org_id "
                "FROM ("
                "  SELECT user_id, MIN(org_id::text)::uuid AS org_id "
                "  FROM user_organization_membership "
                "  WHERE status IN ('accepted', 'active') "
                "  GROUP BY user_id"
                ") uom "
                "WHERE m.org_id IS NULL AND m.created_by_id IS NOT NULL AND uom.user_id = m.created_by_id"
            )
        )

    # Fallback: infer from requester organization membership.
    if _table_exists(bind, "user_organization_membership") and _has_column(bind, "model_registry", "requested_by"):
        bind.execute(
            sa.text(
                "UPDATE model_registry m "
                "SET org_id = uom.org_id "
                "FROM ("
                "  SELECT user_id, MIN(org_id::text)::uuid AS org_id "
                "  FROM user_organization_membership "
                "  WHERE status IN ('accepted', 'active') "
                "  GROUP BY user_id"
                ") uom "
                "WHERE m.org_id IS NULL AND m.requested_by IS NOT NULL AND uom.user_id = m.requested_by"
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return

    for key, category in PERMISSIONS:
        _upsert_permission(bind, key, category)

    # Attach permissions to default roles if present.
    if _table_exists(bind, "role") and _table_exists(bind, "role_permission"):
        role_rows = bind.execute(
            sa.text("SELECT id, name FROM role WHERE name IN :names").bindparams(
                sa.bindparam("names", expanding=True)
            ),
            {"names": list(DEFAULT_ROLE_PERMISSION_ADDITIONS.keys())},
        ).fetchall()
        role_id_by_name = {str(row[1]): str(row[0]) for row in role_rows}

        permission_rows = bind.execute(
            sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(
                sa.bindparam("keys", expanding=True)
            ),
            {"keys": [k for k, _ in PERMISSIONS]},
        ).fetchall()
        permission_id_by_key = {str(row[1]): str(row[0]) for row in permission_rows}

        for role_name, keys in DEFAULT_ROLE_PERMISSION_ADDITIONS.items():
            role_id = role_id_by_name.get(role_name)
            if not role_id:
                continue
            for key in keys:
                permission_id = permission_id_by_key.get(key)
                if not permission_id:
                    continue
                _ensure_role_permission(bind, role_id=role_id, permission_id=permission_id)

    _backfill_model_org_id(bind)


def downgrade() -> None:
    # Non-destructive downgrade.
    return
