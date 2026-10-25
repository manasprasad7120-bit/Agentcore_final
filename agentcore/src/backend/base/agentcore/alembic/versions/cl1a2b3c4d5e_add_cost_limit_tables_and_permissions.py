"""add cost_limit and cost_limit_notification tables with permissions

Revision ID: cl1a2b3c4d5e
Revises: p9q0r1s2t3u4
Create Date: 2026-03-17
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from alembic import op


revision: str = "cl1a2b3c4d5e"
down_revision: str | Sequence[str] | None = "p9q0r1s2t3u4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = [
    ("manage_cost_limits", "Cost Limits"),
    ("view_cost_limits", "Cost Limits"),
]

ROLE_GRANTS = {
    "root": ["manage_cost_limits", "view_cost_limits"],
    "super_admin": ["manage_cost_limits", "view_cost_limits"],
    "department_admin": ["manage_cost_limits", "view_cost_limits"],
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))



def _upsert_permission(bind, key: str, category: str) -> None:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    row = bind.execute(sa.text("SELECT id FROM permission WHERE key = :key"), {"key": key}).fetchone()
    if row:
        set_parts = ["name = :name", "description = :description"]
        params = {"key": key, "name": key.replace("_", " "), "description": None, "category": category, "is_system": True}
        if has_category:
            set_parts.append("category = :category")
        if has_is_system:
            set_parts.append("is_system = :is_system")
        if has_updated_at:
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
        bind.execute(sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"), params)
        return

    cols = ["id", "key", "name", "description"]
    vals = [":id", ":key", ":name", ":description"]
    params = {
        "id": str(uuid4()),
        "key": key,
        "name": key.replace("_", " "),
        "description": None,
        "category": category,
        "is_system": True,
    }
    if has_category:
        cols.append("category")
        vals.append(":category")
    if has_is_system:
        cols.append("is_system")
        vals.append(":is_system")
    if has_created_at:
        cols.append("created_at")
        vals.append("CURRENT_TIMESTAMP")
    if has_updated_at:
        cols.append("updated_at")
        vals.append("CURRENT_TIMESTAMP")
    bind.execute(sa.text(f"INSERT INTO permission ({', '.join(cols)}) VALUES ({', '.join(vals)})"), params)


def upgrade() -> None:
    bind = op.get_bind()

    # ── Create cost_limit table ──
    # Columns use VARCHAR (matching SQLAlchemy models) instead of PostgreSQL
    # enums to avoid type-mismatch issues during future ALTER operations.
    if not _table_exists(bind, "cost_limit"):
        op.create_table(
            "cost_limit",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("scope_type", sa.String(20), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("limit_amount_usd", sa.Numeric(12, 4), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'USD'")),
            sa.Column("period_type", sa.String(20), nullable=False, server_default=sa.text("'monthly'")),
            sa.Column("period_start_day", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("warning_threshold_pct", sa.Integer(), nullable=False, server_default=sa.text("80")),
            sa.Column("action_on_breach", sa.String(30), nullable=False, server_default=sa.text("'notify_only'")),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_breach_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_warning_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_cost_usd", sa.Numeric(12, 4), nullable=True, server_default=sa.text("0")),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_cost_limit_org_id"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_cost_limit_dept_id"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_cost_limit_created_by"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_cost_limit_updated_by"),
            sa.UniqueConstraint("scope_type", "org_id", "dept_id", name="uq_cost_limit_scope"),
            sa.CheckConstraint(
                "(scope_type = 'organization' AND dept_id IS NULL) OR "
                "(scope_type = 'department' AND dept_id IS NOT NULL)",
                name="chk_cost_limit_dept_requires_scope",
            ),
            sa.CheckConstraint("period_start_day BETWEEN 1 AND 28", name="chk_cost_limit_period_start_day"),
            sa.CheckConstraint("warning_threshold_pct BETWEEN 1 AND 100", name="chk_cost_limit_warning_pct"),
        )

    # Indexes for cost_limit
    for idx_name, cols in (
        ("ix_cost_limit_org_id", ["org_id"]),
        ("ix_cost_limit_dept_id", ["dept_id"]),
    ):
        if _table_exists(bind, "cost_limit") and not _has_index(bind, "cost_limit", idx_name):
            op.create_index(idx_name, "cost_limit", cols, unique=False)

    # ── Create cost_limit_notification table ──
    if not _table_exists(bind, "cost_limit_notification"):
        op.create_table(
            "cost_limit_notification",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("cost_limit_id", sa.Uuid(), nullable=False),
            sa.Column("notification_type", sa.String(20), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("cost_at_notification", sa.Numeric(12, 4), nullable=False),
            sa.Column("limit_amount_usd", sa.Numeric(12, 4), nullable=False),
            sa.Column("percentage_used", sa.Numeric(5, 2), nullable=False),
            sa.Column("dismissed_by_user_ids", sa.ARRAY(sa.Uuid()), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["cost_limit_id"], ["cost_limit.id"],
                name="fk_cost_limit_notification_cost_limit_id",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "cost_limit_id", "notification_type", "period_start",
                name="uq_cost_limit_notification_period",
            ),
        )

    if _table_exists(bind, "cost_limit_notification") and not _has_index(bind, "cost_limit_notification", "ix_cost_limit_notification_limit_id"):
        op.create_index("ix_cost_limit_notification_limit_id", "cost_limit_notification", ["cost_limit_id"], unique=False)

    # ── Seed permissions and role grants ──
    if _table_exists(bind, "permission"):
        for key, category in PERMISSIONS:
            _upsert_permission(bind, key, category)

    if _table_exists(bind, "permission") and _table_exists(bind, "role") and _table_exists(bind, "role_permission"):
        role_rows = bind.execute(
            sa.text("SELECT id, name FROM role WHERE name IN :names").bindparams(sa.bindparam("names", expanding=True)),
            {"names": list(ROLE_GRANTS.keys())},
        ).fetchall()
        role_id_by_name = {str(r[1]): str(r[0]) for r in role_rows}

        all_perm_keys = list({k for keys in ROLE_GRANTS.values() for k in keys})
        permission_rows = bind.execute(
            sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
            {"keys": all_perm_keys},
        ).fetchall()
        permission_id_by_key = {str(r[1]): str(r[0]) for r in permission_rows}

        has_created_at = _has_column(bind, "role_permission", "created_at")
        has_updated_at = _has_column(bind, "role_permission", "updated_at")
        has_created_by = _has_column(bind, "role_permission", "created_by")
        has_updated_by = _has_column(bind, "role_permission", "updated_by")

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
                if has_created_by:
                    insert_cols.append("created_by")
                    insert_vals.append("NULL")
                if has_created_at:
                    insert_cols.append("created_at")
                    insert_vals.append("CURRENT_TIMESTAMP")
                if has_updated_by:
                    insert_cols.append("updated_by")
                    insert_vals.append("NULL")
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
                    params,
                )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "cost_limit_notification"):
        try:
            op.drop_index("ix_cost_limit_notification_limit_id", table_name="cost_limit_notification")
        except Exception:
            pass
        op.drop_table("cost_limit_notification")

    if _table_exists(bind, "cost_limit"):
        for idx_name in ("ix_cost_limit_dept_id", "ix_cost_limit_org_id"):
            try:
                op.drop_index(idx_name, table_name="cost_limit")
            except Exception:
                pass
        op.drop_table("cost_limit")



