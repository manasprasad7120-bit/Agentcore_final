"""add guardrail_execution_log table

Revision ID: g3e1x0l9a7b2
Revises: c4066ea5e11e
Create Date: 2026-03-18
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g3e1x0l9a7b2"
down_revision: Union[str, Sequence[str], None] = "c4066ea5e11e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "guardrail_execution_log"):
        op.create_table(
            "guardrail_execution_log",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("guardrail_id", sa.String(length=80), nullable=False, server_default=sa.text("''")),
            sa.Column("agent_id", sa.Uuid(), nullable=True),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("session_id", sa.String(length=255), nullable=True),
            sa.Column("action", sa.String(length=30), nullable=False, server_default=sa.text("'passthrough'")),
            sa.Column("is_violation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("environment", sa.String(length=20), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_gel_agent_id_agent"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_gel_org_id_organization"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_gel_user_id_user"),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in (
        ("ix_gel_org_id", ["org_id"]),
        ("ix_gel_org_violation", ["org_id", "is_violation"]),
    ):
        if _table_exists(bind, "guardrail_execution_log") and not _has_index(bind, "guardrail_execution_log", idx_name):
            op.create_index(idx_name, "guardrail_execution_log", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "guardrail_execution_log"):
        for idx_name in (
            "ix_gel_org_violation",
            "ix_gel_org_id",
        ):
            try:
                op.drop_index(idx_name, table_name="guardrail_execution_log")
            except Exception:
                pass
        op.drop_table("guardrail_execution_log")
