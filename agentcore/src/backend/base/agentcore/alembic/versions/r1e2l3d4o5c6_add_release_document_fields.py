"""add release document metadata fields

Revision ID: r1e2l3d4o5c6
Revises: ap1b2c3d4e5
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "r1e2l3d4o5c6"
down_revision: str | Sequence[str] | None = "ap1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("product_release", schema=None) as batch_op:
        batch_op.add_column(sa.Column("document_file_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("document_storage_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("document_content_type", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("document_size", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("document_uploaded_by", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("document_uploaded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_product_release_document_uploaded_by"),
            ["document_uploaded_by"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_product_release_document_uploaded_by_user",
            "user",
            ["document_uploaded_by"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("product_release", schema=None) as batch_op:
        batch_op.drop_constraint("fk_product_release_document_uploaded_by_user", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_product_release_document_uploaded_by"))
        batch_op.drop_column("document_uploaded_at")
        batch_op.drop_column("document_uploaded_by")
        batch_op.drop_column("document_size")
        batch_op.drop_column("document_content_type")
        batch_op.drop_column("document_storage_path")
        batch_op.drop_column("document_file_name")
