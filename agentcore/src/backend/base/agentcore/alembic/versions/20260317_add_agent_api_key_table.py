"""add agent_api_key table

Revision ID: 20260317_agent_api_key
Revises: 20260316_moved_uat_prod
Create Date: 2026-03-17 00:00:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260317_agent_api_key"
down_revision: Union[str, Sequence[str], None] = "20260316_moved_uat_prod"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_api_key",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "deployment_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("version", sa.String(10), nullable=False, server_default=sa.text("'v1'")),
        sa.Column("environment", sa.String(4), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent.id"],
            name="fk_agent_api_key_agent_id_agent",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"],
            name="fk_agent_api_key_created_by_user",
        ),
    )
    op.create_index("ix_agent_api_key_hash", "agent_api_key", ["key_hash"])
    op.create_index("ix_agent_api_key_agent_env", "agent_api_key", ["agent_id", "environment", "is_active"])
    op.create_index("ix_agent_api_key_deployment", "agent_api_key", ["deployment_id", "is_active"])
    op.create_index("ix_agent_api_key_agent_id", "agent_api_key", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_api_key_agent_id", table_name="agent_api_key")
    op.drop_index("ix_agent_api_key_deployment", table_name="agent_api_key")
    op.drop_index("ix_agent_api_key_agent_env", table_name="agent_api_key")
    op.drop_index("ix_agent_api_key_hash", table_name="agent_api_key")
    op.drop_constraint("fk_agent_api_key_created_by_user", "agent_api_key", type_="foreignkey")
    op.drop_constraint("fk_agent_api_key_agent_id_agent", "agent_api_key", type_="foreignkey")
    op.drop_table("agent_api_key")

