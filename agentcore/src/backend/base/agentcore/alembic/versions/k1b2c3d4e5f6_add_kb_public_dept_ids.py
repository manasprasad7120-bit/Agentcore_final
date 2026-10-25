"""add public_dept_ids to knowledge_base

Revision ID: k1b2c3d4e5f6
Revises: e3f4g5h6i7j8
Create Date: 2026-03-17
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "k1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e3f4g5h6i7j8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "knowledge_base"):
        return
    if not _has_column(bind, "knowledge_base", "public_dept_ids"):
        op.add_column("knowledge_base", sa.Column("public_dept_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "knowledge_base"):
        return
    if _has_column(bind, "knowledge_base", "public_dept_ids"):
        op.drop_column("knowledge_base", "public_dept_ids")

