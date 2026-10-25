"""add rate_limit_rpm and rate_limit_tpm to model_registry

Revision ID: 20260508_rate_limit
Revises: 20260505_merge_all
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260508_rate_limit"
down_revision: Union[str, Sequence[str], None] = "20260505_merge_all"
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
    if not _table_exists(bind, "model_registry"):
        return
    if not _column_exists(bind, "model_registry", "rate_limit_rpm"):
        op.add_column(
            "model_registry",
            sa.Column("rate_limit_rpm", sa.Integer(), nullable=True),
        )
    if not _column_exists(bind, "model_registry", "rate_limit_tpm"):
        op.add_column(
            "model_registry",
            sa.Column("rate_limit_tpm", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "model_registry"):
        return
    if _column_exists(bind, "model_registry", "rate_limit_tpm"):
        op.drop_column("model_registry", "rate_limit_tpm")
    if _column_exists(bind, "model_registry", "rate_limit_rpm"):
        op.drop_column("model_registry", "rate_limit_rpm")
