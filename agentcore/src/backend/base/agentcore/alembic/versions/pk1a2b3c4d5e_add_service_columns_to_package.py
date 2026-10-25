"""add service-aware package inventory columns

Revision ID: pk1a2b3c4d5e
Revises: abc123merge01
Create Date: 2026-03-14 19:00:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pk1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "abc123merge01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "package", "service_name"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("service_name", sa.String(length=100), nullable=True, server_default="backend")
            )

    if not _has_column(bind, "package", "snapshot_id"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(sa.Column("snapshot_id", sa.String(length=100), nullable=True))

    if not _has_column(bind, "package", "build_id"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(sa.Column("build_id", sa.String(length=100), nullable=True))

    if not _has_column(bind, "package", "commit_sha"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(sa.Column("commit_sha", sa.String(length=64), nullable=True))

    op.execute("UPDATE package SET service_name = COALESCE(service_name, 'backend')")

    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.alter_column("service_name", server_default=None, nullable=False)

    if not _has_index(bind, "package", "ix_package_service_name"):
        op.create_index("ix_package_service_name", "package", ["service_name"], unique=False)
    if not _has_index(bind, "package", "ix_package_snapshot_id"):
        op.create_index("ix_package_snapshot_id", "package", ["snapshot_id"], unique=False)
    if not _has_index(bind, "package", "ix_package_name_package_type_service"):
        op.create_index(
            "ix_package_name_package_type_service",
            "package",
            ["name", "package_type", "service_name"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, "package", "ix_package_name_package_type_service"):
        op.drop_index("ix_package_name_package_type_service", table_name="package")
    if _has_index(bind, "package", "ix_package_snapshot_id"):
        op.drop_index("ix_package_snapshot_id", table_name="package")
    if _has_index(bind, "package", "ix_package_service_name"):
        op.drop_index("ix_package_service_name", table_name="package")

    with op.batch_alter_table("package", schema=None) as batch_op:
        if _has_column(bind, "package", "commit_sha"):
            batch_op.drop_column("commit_sha")
        if _has_column(bind, "package", "build_id"):
            batch_op.drop_column("build_id")
        if _has_column(bind, "package", "snapshot_id"):
            batch_op.drop_column("snapshot_id")
        if _has_column(bind, "package", "service_name"):
            batch_op.drop_column("service_name")

