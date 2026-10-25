"""create dataset, dataset_item, dataset_run, dataset_run_item tables

Revision ID: ds20260319001
Revises: z2a3b4c5d6e7
Create Date: 2026-03-19
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ds20260319001"
down_revision: Union[str, Sequence[str], None] = "z2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    # Drop stale tables from prior run (they had mismatched ondelete constraints)
    for stale in ["dataset_run_item", "dataset_run", "dataset_item", "dataset"]:
        if _table_exists(bind, stale):
            op.drop_table(stale)

    # 1. dataset
    op.create_table(
        "dataset",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organization.id"), nullable=True, index=True),
        sa.Column("dept_id", sa.Uuid(), sa.ForeignKey("department.id"), nullable=True, index=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
        sa.Column("public_scope", sa.String(20), nullable=True),
        sa.Column("public_dept_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_dataset_user_name"),
    )

    # 2. dataset_item
    op.create_table(
        "dataset_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("dataset.id"), nullable=False, index=True),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("expected_output", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("source_trace_id", sa.String(255), nullable=True),
        sa.Column("source_observation_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 3. dataset_run
    op.create_table(
        "dataset_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("dataset.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 4. dataset_run_item
    op.create_table(
        "dataset_run_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("dataset_run.id"), nullable=False, index=True),
        sa.Column("dataset_item_id", sa.Uuid(), sa.ForeignKey("dataset_item.id"), nullable=True, index=True),
        sa.Column("trace_id", sa.String(255), nullable=True),
        sa.Column("observation_id", sa.String(255), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ["dataset_run_item", "dataset_run", "dataset_item", "dataset"]:
        if _table_exists(bind, table):
            op.drop_table(table)
