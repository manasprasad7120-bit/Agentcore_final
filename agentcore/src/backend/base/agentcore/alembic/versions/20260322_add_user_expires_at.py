"""Add expires_at column to user table

Revision ID: 20260322_user_expires
Revises: None
Create Date: 2026-03-22

Adds an optional nullable timestamp column `expires_at` to the user table.
When set, the user will be auto-deactivated upon login after the expiry time.
If not set, the user has no expiry.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260322_user_expires"
down_revision = None  # standalone; picked up by next merge head
branch_labels = ("user_expires_at",)
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "user") and not _has_column(bind, "user", "expires_at"):
        op.add_column(
            "user",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "user") and _has_column(bind, "user", "expires_at"):
        op.drop_column("user", "expires_at")
