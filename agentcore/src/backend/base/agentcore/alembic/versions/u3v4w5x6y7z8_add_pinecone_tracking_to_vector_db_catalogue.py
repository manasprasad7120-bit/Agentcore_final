"""add pinecone tracking columns to vector_db_catalogue

Revision ID: u3v4w5x6y7z8
Revises: d2c10200ff01
Create Date: 2026-03-11 18:00:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "u3v4w5x6y7z8"
down_revision: Union[str, Sequence[str], None] = "d2c10200ff01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(bind).get_indexes(table_name))


def _has_fk(bind, table_name: str, name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(fk["name"] == name for fk in sa.inspect(bind).get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "vector_db_catalogue"):
        return

    # Environment: uat / prod
    if not _has_column(bind, "vector_db_catalogue", "environment"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("environment", sa.String(10), nullable=True, server_default="uat"),
        )

    # Pinecone-specific tracking
    if not _has_column(bind, "vector_db_catalogue", "index_name"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("index_name", sa.String(256), nullable=True),
        )
    if not _has_column(bind, "vector_db_catalogue", "namespace"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("namespace", sa.String(256), nullable=True),
        )

    # Agent association
    if not _has_column(bind, "vector_db_catalogue", "agent_id"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("agent_id", sa.Uuid(), nullable=True),
        )
    if not _has_column(bind, "vector_db_catalogue", "agent_name"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("agent_name", sa.String(255), nullable=True),
        )

    # UAT → PROD lineage
    if not _has_column(bind, "vector_db_catalogue", "source_entry_id"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("source_entry_id", sa.Uuid(), nullable=True),
        )

    # Migration tracking
    if not _has_column(bind, "vector_db_catalogue", "migration_status"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("migration_status", sa.String(50), nullable=True),
        )
    if not _has_column(bind, "vector_db_catalogue", "migrated_at"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_column(bind, "vector_db_catalogue", "vectors_copied"):
        op.add_column(
            "vector_db_catalogue",
            sa.Column("vectors_copied", sa.Integer(), nullable=True, server_default="0"),
        )

    # Indexes
    if not _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_environment"):
        op.create_index(
            "ix_vector_db_catalogue_environment",
            "vector_db_catalogue",
            ["environment"],
        )
    if not _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_agent_id"):
        op.create_index(
            "ix_vector_db_catalogue_agent_id",
            "vector_db_catalogue",
            ["agent_id"],
        )

    # Self-referencing FK for lineage
    if not _has_fk(bind, "vector_db_catalogue", "fk_vector_db_source_entry"):
        op.create_foreign_key(
            "fk_vector_db_source_entry",
            "vector_db_catalogue",
            "vector_db_catalogue",
            ["source_entry_id"],
            ["id"],
        )

    # Backfill: set existing rows to 'uat' environment
    op.execute("UPDATE vector_db_catalogue SET environment = 'uat' WHERE environment IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "vector_db_catalogue"):
        return

    if _has_fk(bind, "vector_db_catalogue", "fk_vector_db_source_entry"):
        op.drop_constraint("fk_vector_db_source_entry", "vector_db_catalogue", type_="foreignkey")

    if _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_agent_id"):
        op.drop_index("ix_vector_db_catalogue_agent_id", table_name="vector_db_catalogue")
    if _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_environment"):
        op.drop_index("ix_vector_db_catalogue_environment", table_name="vector_db_catalogue")

    for col in ("vectors_copied", "migrated_at", "migration_status", "source_entry_id",
                "agent_name", "agent_id", "namespace", "index_name", "environment"):
        if _has_column(bind, "vector_db_catalogue", col):
            op.drop_column("vector_db_catalogue", col)

