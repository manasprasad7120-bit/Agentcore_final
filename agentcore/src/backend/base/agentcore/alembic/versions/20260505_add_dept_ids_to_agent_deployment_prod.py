"""Add dept_ids to agent_deployment_prod for super-admin multi-dept PROD publishes

Revision ID: 20260505_adp_add_dept_ids
Revises: 20260505_apr_add_deploy_id
Create Date: 2026-05-05

Adds a nullable JSON column `dept_ids` to `agent_deployment_prod` so that a
super admin can tag a single PROD deployment with multiple department IDs.
The primary `dept_id` column remains the canonical/first dept; `dept_ids`
holds the full list (including the primary) as a JSON array of UUID strings.

Existing rows keep `dept_ids = NULL` and are unaffected.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260505_adp_add_dept_ids"
down_revision: Union[str, Sequence[str], None] = "20260505_apr_add_deploy_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table: str, column: str) -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "agent_deployment_prod", "dept_ids"):
        op.add_column(
            "agent_deployment_prod",
            sa.Column("dept_ids", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, "agent_deployment_prod", "dept_ids"):
        op.drop_column("agent_deployment_prod", "dept_ids")
