"""Add environments array to MCP registry and requested_environments to MCP approvals.

Revision ID: b7c8d9e0f1a2
Revises: e2f3a4b5c6d8
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "e2f3a4b5c6d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mcp_registry", sa.Column("environments", sa.JSON(), nullable=True))
    op.add_column("mcp_approval_request", sa.Column("requested_environments", sa.JSON(), nullable=True))

    # Update defaults to UAT
    op.alter_column("mcp_registry", "deployment_env", server_default="UAT")
    op.alter_column("mcp_approval_request", "deployment_env", server_default="UAT")

    # Backfill environments from deployment_env (DEV/TEST -> UAT)
    op.execute(
        """
        UPDATE mcp_registry
        SET environments = to_json(ARRAY[
            lower(CASE WHEN deployment_env IN ('DEV','TEST') THEN 'UAT' ELSE deployment_env END)
        ])
        WHERE environments IS NULL
        """
    )

    op.execute(
        """
        UPDATE mcp_approval_request
        SET requested_environments = to_json(ARRAY[
            lower(CASE WHEN deployment_env IN ('DEV','TEST') THEN 'UAT' ELSE deployment_env END)
        ])
        WHERE requested_environments IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("mcp_approval_request", "requested_environments")
    op.drop_column("mcp_registry", "environments")

    op.alter_column("mcp_approval_request", "deployment_env", server_default="DEV")
    op.alter_column("mcp_registry", "deployment_env", server_default="DEV")
