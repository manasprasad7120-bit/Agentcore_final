"""add service_name to release_package_snapshot

Revision ID: pk2b3c4d5e6f
Revises: pk1a2b3c4d5e
Create Date: 2026-03-14 20:10:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "pk2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "pk1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def _has_unique_constraint(bind, table_name: str, constraint_name: str) -> bool:
    return any(c.get("name") == constraint_name for c in sa.inspect(bind).get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "release_package_snapshot", "service_name"):
        with op.batch_alter_table("release_package_snapshot", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("service_name", sa.String(length=100), nullable=True, server_default="backend")
            )

    op.execute("UPDATE release_package_snapshot SET service_name = COALESCE(service_name, 'backend')")

    with op.batch_alter_table("release_package_snapshot", schema=None) as batch_op:
        batch_op.alter_column("service_name", nullable=False, server_default=None)

    if _has_unique_constraint(bind, "release_package_snapshot", "uq_release_package_snapshot_release_name_type"):
        op.drop_constraint(
            "uq_release_package_snapshot_release_name_type",
            "release_package_snapshot",
            type_="unique",
        )

    if not _has_unique_constraint(
        bind,
        "release_package_snapshot",
        "uq_release_package_snapshot_release_service_name_type",
    ):
        op.create_unique_constraint(
            "uq_release_package_snapshot_release_service_name_type",
            "release_package_snapshot",
            ["release_id", "service_name", "name", "package_type"],
        )

    if not _has_index(bind, "release_package_snapshot", "ix_release_package_snapshot_service_name"):
        op.create_index(
            "ix_release_package_snapshot_service_name",
            "release_package_snapshot",
            ["service_name"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, "release_package_snapshot", "ix_release_package_snapshot_service_name"):
        op.drop_index("ix_release_package_snapshot_service_name", table_name="release_package_snapshot")

    if _has_unique_constraint(
        bind,
        "release_package_snapshot",
        "uq_release_package_snapshot_release_service_name_type",
    ):
        op.drop_constraint(
            "uq_release_package_snapshot_release_service_name_type",
            "release_package_snapshot",
            type_="unique",
        )

    if not _has_unique_constraint(bind, "release_package_snapshot", "uq_release_package_snapshot_release_name_type"):
        op.create_unique_constraint(
            "uq_release_package_snapshot_release_name_type",
            "release_package_snapshot",
            ["release_id", "name", "package_type"],
        )

    if _has_column(bind, "release_package_snapshot", "service_name"):
        with op.batch_alter_table("release_package_snapshot", schema=None) as batch_op:
            batch_op.drop_column("service_name")

