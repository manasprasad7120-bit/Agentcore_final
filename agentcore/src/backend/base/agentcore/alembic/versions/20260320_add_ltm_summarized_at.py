"""Add ltm_summarized_at column to all conversation tables

Revision ID: ltm001_summarized_at
Revises: None
Create Date: 2026-03-20

Adds a nullable timestamp column `ltm_summarized_at` to all 4 conversation
tables. The LTM pipeline sets this after summarizing a message, so it is
never re-summarized regardless of Redis state, server restarts, or TTL expiry.

On upgrade: all EXISTING rows are marked with NOW() so the pipeline only
processes NEW messages going forward (existing Pinecone summaries cover history).
"""

from alembic import op
import sqlalchemy as sa

revision = "ltm001_summarized_at"
down_revision = None  # standalone; picked up by next merge head
branch_labels = ("ltm_summarized_at",)
depends_on = None

_TABLES = ("conversation", "orch_conversation", "conversation_prod", "conversation_uat")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("ltm_summarized_at", sa.DateTime(timezone=False), nullable=True),
        )
    # Mark all pre-existing messages as already summarized so the pipeline
    # starts fresh with only new messages.
    for table in _TABLES:
        op.execute(
            f"UPDATE {table} SET ltm_summarized_at = NOW() WHERE ltm_summarized_at IS NULL"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "ltm_summarized_at")
