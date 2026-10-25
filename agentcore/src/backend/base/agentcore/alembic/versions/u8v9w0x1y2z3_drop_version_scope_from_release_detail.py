"""drop version_scope from release_detail

Revision ID: u8v9w0x1y2z3
Revises: t9u8v7w6x5y4
Create Date: 2026-03-11 23:59:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "u8v9w0x1y2z3"
down_revision: Union[str, Sequence[str], None] = "t9u8v7w6x5y4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "release_detail", "version_scope"):
        return

    with op.batch_alter_table("release_detail", schema=None) as batch_op:
        batch_op.drop_column("version_scope")


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "release_detail", "version_scope"):
        return

    with op.batch_alter_table("release_detail", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("version_scope", sa.String(length=20), nullable=False, server_default="latest")
        )
        batch_op.alter_column("version_scope", server_default=None)

