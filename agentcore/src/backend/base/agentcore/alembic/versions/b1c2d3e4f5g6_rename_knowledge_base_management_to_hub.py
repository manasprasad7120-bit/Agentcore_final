"""
Revision ID: b1c2d3e4f5g6
Revises: z9y8x7w6v5u4
Create Date: 2026-03-17 20:45:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5g6"
down_revision: Union[str, Sequence[str], None] = "z9y8x7w6v5u4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _update_category(bind, new_value: str) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE permission
            SET category = :category
            WHERE key IN ('view_knowledge_base', 'add_new_knowledge')
            """
        ),
        {"category": new_value},
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return
    if not _has_column(bind, "permission", "category"):
        return
    _update_category(bind, "Knowledge Hub")


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return
    if not _has_column(bind, "permission", "category"):
        return
    _update_category(bind, "Knowledge Base Management")

