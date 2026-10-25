"""add model_id and reasoning_content to orch_conversation

Revision ID: m1d2r3c4t5o6
Revises: aedb98eb5b0b
Create Date: 2026-04-07
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m1d2r3c4t5o6"
down_revision: Union[str, Sequence[str], None] = "aedb98eb5b0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    cols = [c["name"] for c in sa.inspect(bind).get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "orch_conversation"):
        if not _column_exists(bind, "orch_conversation", "model_id"):
            op.add_column("orch_conversation", sa.Column("model_id", sa.Uuid(), nullable=True))
        if not _column_exists(bind, "orch_conversation", "reasoning_content"):
            op.add_column("orch_conversation", sa.Column("reasoning_content", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "orch_conversation"):
        if _column_exists(bind, "orch_conversation", "reasoning_content"):
            op.drop_column("orch_conversation", "reasoning_content")
        if _column_exists(bind, "orch_conversation", "model_id"):
            op.drop_column("orch_conversation", "model_id")
