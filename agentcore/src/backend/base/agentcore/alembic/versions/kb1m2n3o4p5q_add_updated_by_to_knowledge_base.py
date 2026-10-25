"""add updated_by to knowledge_base

Adds a nullable updated_by column to knowledge_base so the UI can show who
last modified each KB (the typical case is another user uploading files into
a public KB). Existing rows receive NULL.

Revision ID: kb1m2n3o4p5q
Revises: fb1k2m3n4o5p
Create Date: 2026-04-27
"""

from __future__ import annotations
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "kb1m2n3o4p5q"
down_revision: Union[str, Sequence[str], None] = "fb1k2m3n4o5p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "knowledge_base"):
        return
    if not _has_column(bind, "knowledge_base", "updated_by"):
        op.add_column(
            "knowledge_base",
            sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_knowledge_base_updated_by_user",
            source_table="knowledge_base",
            referent_table="user",
            local_cols=["updated_by"],
            remote_cols=["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "knowledge_base"):
        return
    if _has_column(bind, "knowledge_base", "updated_by"):
        try:
            op.drop_constraint(
                "fk_knowledge_base_updated_by_user",
                "knowledge_base",
                type_="foreignkey",
            )
        except Exception:
            pass
        op.drop_column("knowledge_base", "updated_by")
