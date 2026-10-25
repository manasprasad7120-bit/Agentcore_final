"""create release_detail table

Revision ID: t9u8v7w6x5y4
Revises: s1u2v3w4x5y6
Create Date: 2026-03-11 21:30:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t9u8v7w6x5y4"
down_revision: Union[str, Sequence[str], None] = "s1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "release_detail" in inspector.get_table_names():
        return

    op.create_table(
        "release_detail",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("section_no", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(length=255), nullable=True),
        sa.Column("module", sa.String(length=255), nullable=True),
        sa.Column("sub_module", sa.String(length=255), nullable=True),
        sa.Column("feature_capability", sa.String(length=500), nullable=False),
        sa.Column("description_details", sa.Text(), nullable=True),
        sa.Column("version_scope", sa.String(length=20), nullable=False, server_default="latest"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["product_release.id"],
            name="fk_release_detail_release_id_product_release",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("release_detail", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_release_detail_release_id"), ["release_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_release_detail_sort_order"), ["sort_order"], unique=False)
        batch_op.alter_column("version_scope", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "release_detail" not in inspector.get_table_names():
        return

    with op.batch_alter_table("release_detail", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_detail_sort_order"))
        batch_op.drop_index(batch_op.f("ix_release_detail_release_id"))

    op.drop_table("release_detail")

