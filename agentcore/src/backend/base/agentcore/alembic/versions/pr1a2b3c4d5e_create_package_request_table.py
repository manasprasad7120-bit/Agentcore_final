"""create package_request table

Revision ID: pr1a2b3c4d5e
Revises: pk2b3c4d5e6f
Create Date: 2026-03-14 22:30:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pr1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "pk2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "package_request"):
        op.create_table(
            "package_request",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("service_name", sa.String(length=100), nullable=False),
            sa.Column("package_name", sa.String(length=255), nullable=False),
            sa.Column("requested_version", sa.String(length=100), nullable=False),
            sa.Column("justification", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
            sa.Column("requested_by", sa.Uuid(), nullable=False),
            sa.Column("reviewed_by", sa.Uuid(), nullable=True),
            sa.Column("deployed_by", sa.Uuid(), nullable=True),
            sa.Column("review_comments", sa.Text(), nullable=True),
            sa.Column("deployment_notes", sa.Text(), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["requested_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["reviewed_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["deployed_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index(bind, "package_request", "ix_package_request_service_name"):
        op.create_index("ix_package_request_service_name", "package_request", ["service_name"], unique=False)
    if not _has_index(bind, "package_request", "ix_package_request_package_name"):
        op.create_index("ix_package_request_package_name", "package_request", ["package_name"], unique=False)
    if not _has_index(bind, "package_request", "ix_package_request_status"):
        op.create_index("ix_package_request_status", "package_request", ["status"], unique=False)
    if not _has_index(bind, "package_request", "ix_package_request_requested_by"):
        op.create_index("ix_package_request_requested_by", "package_request", ["requested_by"], unique=False)
    if not _has_index(bind, "package_request", "ix_package_request_reviewed_by"):
        op.create_index("ix_package_request_reviewed_by", "package_request", ["reviewed_by"], unique=False)
    if not _has_index(bind, "package_request", "ix_package_request_deployed_by"):
        op.create_index("ix_package_request_deployed_by", "package_request", ["deployed_by"], unique=False)
    if not _has_index(bind, "package_request", "ix_package_request_service_status"):
        op.create_index(
            "ix_package_request_service_status",
            "package_request",
            ["service_name", "status"],
            unique=False,
        )
    if not _has_index(bind, "package_request", "ix_package_request_package_status"):
        op.create_index(
            "ix_package_request_package_status",
            "package_request",
            ["package_name", "status"],
            unique=False,
        )

    op.execute("ALTER TABLE package_request ALTER COLUMN status DROP DEFAULT")


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "package_request"):
        op.drop_table("package_request")


