"""
Revision ID: b3c4d5e6f7g8
Revises: u8v9w0x1y2z3
Create Date: 2026-03-14
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b3c4d5e6f7g8"
down_revision: Union[str, Sequence[str], None] = "u8v9w0x1y2z3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "approval_request",
    "mcp_approval_request",
    "model_approval_request",
)


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any((fk.get("name") or "") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if not _table_exists(bind, table):
            continue
        if not _has_column(bind, table, "reviewed_by"):
            op.add_column(table, sa.Column("reviewed_by", sa.Uuid(), nullable=True))

    fk_specs = (
        ("fk_approval_request_reviewed_by_user", "approval_request"),
        ("fk_mcp_approval_request_reviewed_by_user", "mcp_approval_request"),
        ("fk_model_approval_request_reviewed_by_user", "model_approval_request"),
    )
    for fk_name, table in fk_specs:
        if _table_exists(bind, table) and not _has_fk(bind, table, fk_name):
            op.create_foreign_key(
                fk_name,
                table,
                "user",
                ["reviewed_by"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    fk_specs = (
        ("fk_approval_request_reviewed_by_user", "approval_request"),
        ("fk_mcp_approval_request_reviewed_by_user", "mcp_approval_request"),
        ("fk_model_approval_request_reviewed_by_user", "model_approval_request"),
    )
    for fk_name, table in fk_specs:
        if _table_exists(bind, table) and _has_fk(bind, table, fk_name):
            op.drop_constraint(fk_name, table, type_="foreignkey")

    for table in TABLES:
        if _table_exists(bind, table) and _has_column(bind, table, "reviewed_by"):
            op.drop_column(table, "reviewed_by")

