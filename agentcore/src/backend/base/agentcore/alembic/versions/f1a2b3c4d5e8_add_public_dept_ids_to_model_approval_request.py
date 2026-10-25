"""add public_dept_ids to model_approval_request

Revision ID: f1a2b3c4d5e8
Revises: f1a2b3c4d5e7
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "f1a2b3c4d5e8"
down_revision = "f1a2b3c4d5e7"
branch_labels = None
depends_on = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "model_approval_request", "public_dept_ids"):
        op.add_column("model_approval_request", sa.Column("public_dept_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "model_approval_request", "public_dept_ids"):
        op.drop_column("model_approval_request", "public_dept_ids")
