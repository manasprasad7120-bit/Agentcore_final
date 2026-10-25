"""add tools count tracking to mcp registry

Revision ID: e3f4g5h6i7j8
Revises: d3e4f5a6b7c8
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e3f4g5h6i7j8"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mcp_registry", sa.Column("tools_count", sa.Integer(), nullable=True))
    op.add_column(
        "mcp_registry",
        sa.Column("tools_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("mcp_registry", sa.Column("tools_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_registry", "tools_snapshot")
    op.drop_column("mcp_registry", "tools_checked_at")
    op.drop_column("mcp_registry", "tools_count")
