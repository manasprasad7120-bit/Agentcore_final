"""create approval notification table

Revision ID: ap1b2c3d4e5
Revises: 0c436763acb9
Create Date: 2026-03-23 18:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ap1b2c3d4e5"
down_revision: Union[str, None] = "0c436763acb9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipient_user_id",
            "entity_type",
            "entity_id",
            name="uq_approval_notification_recipient_entity",
        ),
    )
    op.create_index(
        "ix_approval_notification_recipient_user_id",
        "approval_notification",
        ["recipient_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_notification_is_read",
        "approval_notification",
        ["is_read"],
        unique=False,
    )
    op.create_index(
        "ix_approval_notification_recipient_created",
        "approval_notification",
        ["recipient_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_approval_notification_recipient_created", table_name="approval_notification")
    op.drop_index("ix_approval_notification_is_read", table_name="approval_notification")
    op.drop_index("ix_approval_notification_recipient_user_id", table_name="approval_notification")
    op.drop_table("approval_notification")
