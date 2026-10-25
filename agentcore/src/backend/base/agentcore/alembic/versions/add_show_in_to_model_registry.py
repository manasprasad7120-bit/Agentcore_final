"""add show_in to model_registry

Revision ID: s1h2o3w4i5n6
Revises: m1d2r3c4t5o6
Create Date: 2026-04-09
"""

from __future__ import annotations
from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s1h2o3w4i5n6"
down_revision: Union[str, Sequence[str], None] = "m1d2r3c4t5o6"
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
    if _table_exists(bind, "model_registry"):
        if not _column_exists(bind, "model_registry", "show_in"):
            op.add_column("model_registry", sa.Column("show_in", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "model_registry"):
        if _column_exists(bind, "model_registry", "show_in"):
            op.drop_column("model_registry", "show_in")
