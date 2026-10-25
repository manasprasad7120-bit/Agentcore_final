"""add moved_to_prod to agent_deployment_uat

Revision ID: 20260316_moved_uat_prod
Revises: abc123merge01
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260316_moved_uat_prod"
down_revision = "abc123merge01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_deployment_uat",
        sa.Column("moved_to_prod", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        """
        UPDATE agent_deployment_uat u
        SET moved_to_prod = true
        WHERE EXISTS (
            SELECT 1 FROM agent_deployment_prod p
            WHERE p.promoted_from_uat_id = u.id
        )
        """
    )
    op.execute("ALTER TABLE agent_deployment_uat ALTER COLUMN moved_to_prod DROP DEFAULT")


def downgrade() -> None:
    op.drop_column("agent_deployment_uat", "moved_to_prod")
