"""alter knowledge_base public_dept_ids to jsonb

Revision ID: k1b2c3d4e5f7
Revises: k1b2c3d4e5f6
Create Date: 2026-03-17
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "k1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "k1b2c3d4e5f6"
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
    if bind.dialect.name != "postgresql":
        return
    if not _table_exists(bind, "knowledge_base"):
        return
    if not _has_column(bind, "knowledge_base", "public_dept_ids"):
        op.add_column("knowledge_base", sa.Column("public_dept_ids", postgresql.JSONB(), nullable=True))
        return
    op.alter_column(
        "knowledge_base",
        "public_dept_ids",
        type_=postgresql.JSONB(),
        postgresql_using="public_dept_ids::jsonb",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _table_exists(bind, "knowledge_base"):
        return
    if _has_column(bind, "knowledge_base", "public_dept_ids"):
        op.alter_column(
            "knowledge_base",
            "public_dept_ids",
            type_=sa.JSON(),
            postgresql_using="public_dept_ids::json",
        )

