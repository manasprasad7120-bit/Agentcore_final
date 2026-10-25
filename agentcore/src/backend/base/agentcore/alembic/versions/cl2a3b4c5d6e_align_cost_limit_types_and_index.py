"""align cost_limit columns and index names to models

Revision ID: cl2a3b4c5d6e
Revises: cl1a2b3c4d5e
Create Date: 2026-03-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "cl2a3b4c5d6e"
down_revision: str | Sequence[str] | None = "cl1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    # Align index name with naming convention
    if _has_index(bind, "cost_limit_notification", "ix_cost_limit_notification_limit_id"):
        op.drop_index("ix_cost_limit_notification_limit_id", table_name="cost_limit_notification")
    if not _has_index(bind, "cost_limit_notification", "ix_cost_limit_notification_cost_limit_id"):
        op.create_index(
            "ix_cost_limit_notification_cost_limit_id",
            "cost_limit_notification",
            ["cost_limit_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Revert index name
    if _has_index(bind, "cost_limit_notification", "ix_cost_limit_notification_cost_limit_id"):
        op.drop_index("ix_cost_limit_notification_cost_limit_id", table_name="cost_limit_notification")
    if not _has_index(bind, "cost_limit_notification", "ix_cost_limit_notification_limit_id"):
        op.create_index(
            "ix_cost_limit_notification_limit_id",
            "cost_limit_notification",
            ["cost_limit_id"],
            unique=False,
        )
