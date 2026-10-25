"""Add MCP approval requested visibility fields.

Revision ID: d2e3f4g5h6i7
Revises: c1d2e3f4g5h6
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d2e3f4g5h6i7"
down_revision = "c1d2e3f4g5h6"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "mcp_approval_request"):
        return

    if not _has_column(bind, "mcp_approval_request", "requested_visibility"):
        op.add_column("mcp_approval_request", sa.Column("requested_visibility", sa.String(length=20), nullable=True))
    if not _has_column(bind, "mcp_approval_request", "requested_public_scope"):
        op.add_column("mcp_approval_request", sa.Column("requested_public_scope", sa.String(length=20), nullable=True))
    if not _has_column(bind, "mcp_approval_request", "requested_org_id"):
        op.add_column("mcp_approval_request", sa.Column("requested_org_id", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_approval_request", "requested_dept_id"):
        op.add_column("mcp_approval_request", sa.Column("requested_dept_id", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_approval_request", "requested_public_dept_ids"):
        op.add_column("mcp_approval_request", sa.Column("requested_public_dept_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Non-destructive downgrade: keep columns if they exist.
    return
