"""drop evaluator RBAC columns (visibility, public_scope, org_id, dept_id, shared_user_ids, public_dept_ids)

Revision ID: ds20260319002
Revises: c2e3ab23da8c
Create Date: 2026-03-19
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ds20260319002"
down_revision: Union[str, Sequence[str], None] = "c2e3ab23da8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "evaluator"):
        return

    # Drop foreign keys first
    inspector = sa.inspect(bind)
    fks = inspector.get_foreign_keys("evaluator")
    for fk in fks:
        if fk.get("constrained_columns") in [["org_id"], ["dept_id"]]:
            if fk.get("name"):
                op.drop_constraint(fk["name"], "evaluator", type_="foreignkey")

    # Drop indexes
    indexes = inspector.get_indexes("evaluator")
    for idx in indexes:
        if idx.get("column_names") in [["org_id"], ["dept_id"]]:
            if idx.get("name"):
                op.drop_index(idx["name"], table_name="evaluator")

    # Drop columns
    for col in ["visibility", "public_scope", "shared_user_ids", "public_dept_ids", "org_id", "dept_id"]:
        if _has_column(bind, "evaluator", col):
            op.drop_column("evaluator", col)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "evaluator"):
        return

    if not _has_column(bind, "evaluator", "visibility"):
        op.add_column("evaluator", sa.Column("visibility", sa.String(20), nullable=False, server_default="private"))
    if not _has_column(bind, "evaluator", "public_scope"):
        op.add_column("evaluator", sa.Column("public_scope", sa.String(20), nullable=True))
    if not _has_column(bind, "evaluator", "shared_user_ids"):
        op.add_column("evaluator", sa.Column("shared_user_ids", sa.JSON(), nullable=True))
    if not _has_column(bind, "evaluator", "public_dept_ids"):
        op.add_column("evaluator", sa.Column("public_dept_ids", sa.JSON(), nullable=True))
    if not _has_column(bind, "evaluator", "org_id"):
        op.add_column("evaluator", sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organization.id"), nullable=True, index=True))
    if not _has_column(bind, "evaluator", "dept_id"):
        op.add_column("evaluator", sa.Column("dept_id", sa.Uuid(), sa.ForeignKey("department.id"), nullable=True, index=True))
