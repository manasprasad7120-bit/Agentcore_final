"""add release document hash

Revision ID: r6e7l8h9a0s1
Revises: r1e2l3d4o5c6
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "r6e7l8h9a0s1"
down_revision: str | Sequence[str] | None = "r1e2l3d4o5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("product_release", schema=None) as batch_op:
        batch_op.add_column(sa.Column("document_hash", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_product_release_document_hash"), ["document_hash"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("product_release", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_product_release_document_hash"))
        batch_op.drop_column("document_hash")
