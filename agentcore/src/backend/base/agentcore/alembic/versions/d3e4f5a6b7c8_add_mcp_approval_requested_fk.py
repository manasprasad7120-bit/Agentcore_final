"""Add FK constraints for MCP approval requested org/dept.

Revision ID: d3e4f5a6b7c8
Revises: d2e3f4g5h6i7
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d3e4f5a6b7c8"
down_revision = "d2e3f4g5h6i7"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any((fk.get("name") or "") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    table_name = "mcp_approval_request"
    if not _table_exists(bind, table_name):
        return

    if _has_column(bind, table_name, "requested_org_id") and not _has_fk(
        bind, table_name, "fk_mcp_approval_request_requested_org_id_organization"
    ):
        op.create_foreign_key(
            "fk_mcp_approval_request_requested_org_id_organization",
            table_name,
            "organization",
            ["requested_org_id"],
            ["id"],
        )

    if _has_column(bind, table_name, "requested_dept_id") and not _has_fk(
        bind, table_name, "fk_mcp_approval_request_requested_dept_id_department"
    ):
        op.create_foreign_key(
            "fk_mcp_approval_request_requested_dept_id_department",
            table_name,
            "department",
            ["requested_dept_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    table_name = "mcp_approval_request"
    if not _table_exists(bind, table_name):
        return

    if _has_fk(bind, table_name, "fk_mcp_approval_request_requested_dept_id_department"):
        op.drop_constraint(
            "fk_mcp_approval_request_requested_dept_id_department",
            table_name,
            type_="foreignkey",
        )
    if _has_fk(bind, table_name, "fk_mcp_approval_request_requested_org_id_organization"):
        op.drop_constraint(
            "fk_mcp_approval_request_requested_org_id_organization",
            table_name,
            type_="foreignkey",
        )
