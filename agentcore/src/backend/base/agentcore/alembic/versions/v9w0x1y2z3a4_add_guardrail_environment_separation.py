"""add guardrail environment separation columns

Adds environment, source_guardrail_id, promoted_at, promoted_by,
and prod_ref_count columns to guardrail_catalogue for UAT/PROD
environment separation. Backfills all existing rows with environment='uat'.

Updates the unique constraint from (org_id, dept_id, name) to
(org_id, dept_id, name, environment) to allow both a UAT and PROD
copy of the same guardrail to coexist.

Revision ID: v9w0x1y2z3a4
Revises: u8v9w0x1y2z3
Create Date: 2026-03-12 12:00:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "v9w0x1y2z3a4"
down_revision: Union[str, Sequence[str], None] = "u8v9w0x1y2z3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _has_unique_constraint(bind, table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(uc["name"] == constraint_name for uc in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    # ── Add new columns ──

    if not _has_column(bind, "guardrail_catalogue", "environment"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("environment", sa.String(length=10), nullable=False, server_default="uat"),
        )

    if not _has_column(bind, "guardrail_catalogue", "source_guardrail_id"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("source_guardrail_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )

    if not _has_column(bind, "guardrail_catalogue", "promoted_at"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_column(bind, "guardrail_catalogue", "promoted_by"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("promoted_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )

    if not _has_column(bind, "guardrail_catalogue", "prod_ref_count"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("prod_ref_count", sa.Integer(), nullable=False, server_default="0"),
        )

    # ── Create indexes ──

    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_environment"):
        op.create_index(
            "ix_guardrail_catalogue_environment",
            "guardrail_catalogue",
            ["environment"],
        )

    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_source_guardrail_id"):
        op.create_index(
            "ix_guardrail_source_guardrail_id",
            "guardrail_catalogue",
            ["source_guardrail_id"],
        )

    # ── Update unique constraint: (org_id, dept_id, name) → (org_id, dept_id, name, environment) ──

    if _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name"):
        op.drop_constraint("uq_guardrail_scope_name", "guardrail_catalogue", type_="unique")

    if not _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name_env"):
        op.create_unique_constraint(
            "uq_guardrail_scope_name_env",
            "guardrail_catalogue",
            ["org_id", "dept_id", "name", "environment"],
        )

    # ── Backfill: all existing rows → environment='uat' ──
    # (server_default already handles this for new rows, but explicit backfill
    # ensures any rows inserted between column-add and this statement are covered)
    op.execute("UPDATE guardrail_catalogue SET environment = 'uat' WHERE environment IS NULL OR environment = ''")

    # Remove server defaults after backfill (model defines Python-level defaults)
    op.alter_column("guardrail_catalogue", "environment", server_default=None)
    op.alter_column("guardrail_catalogue", "prod_ref_count", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    # Delete prod copies before removing columns
    op.execute("DELETE FROM guardrail_catalogue WHERE environment = 'prod'")

    # Restore original unique constraint
    if _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name_env"):
        op.drop_constraint("uq_guardrail_scope_name_env", "guardrail_catalogue", type_="unique")

    if not _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name"):
        op.create_unique_constraint(
            "uq_guardrail_scope_name",
            "guardrail_catalogue",
            ["org_id", "dept_id", "name"],
        )

    # Drop indexes
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_source_guardrail_id"):
        op.drop_index("ix_guardrail_source_guardrail_id", "guardrail_catalogue")

    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_environment"):
        op.drop_index("ix_guardrail_catalogue_environment", "guardrail_catalogue")

    # Drop columns
    for col in ("prod_ref_count", "promoted_by", "promoted_at", "source_guardrail_id", "environment"):
        if _has_column(bind, "guardrail_catalogue", col):
            op.drop_column("guardrail_catalogue", col)

