"""scope file.name unique constraint to (user_id, knowledge_base_id, name)

Revision ID: 20260511_scope_file
Revises: 20260508_rate_limit
Create Date: 2026-05-11

Replaces the legacy global ``UNIQUE(name)`` constraint on ``file`` with a
composite ``UNIQUE(user_id, knowledge_base_id, name)``. Without this, a fresh
KB cannot accept a filename that already exists in any other KB on the same
deployment, which forces the upload pipeline to rename files even when the
target KB is empty.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260511_scope_file"
down_revision: Union[str, Sequence[str], None] = "20260508_rate_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_CONSTRAINT_NAME = "uq_file_user_kb_name"
LEGACY_CONSTRAINT_NAME = "uq_file_name"


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _unique_constraint_on(bind, table_name: str, columns: list[str]) -> str | None:
    """Return the name of any UNIQUE constraint covering exactly ``columns``."""
    target = sorted(columns)
    for c in sa.inspect(bind).get_unique_constraints(table_name):
        if sorted(c.get("column_names") or []) == target:
            return c.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "file"):
        return

    has_kb_id = _column_exists(bind, "file", "knowledge_base_id")
    new_columns = (
        ["user_id", "knowledge_base_id", "name"] if has_kb_id else ["user_id", "name"]
    )

    # Resolve names BEFORE entering batch_alter_table — under SQLite the batch
    # works on a copied table and reflection inside the context can return a
    # different shape than the live table.
    legacy_name = _unique_constraint_on(bind, "file", ["name"])
    already_scoped = _unique_constraint_on(bind, "file", new_columns)

    with op.batch_alter_table("file", schema=None) as batch_op:
        if legacy_name:
            batch_op.drop_constraint(legacy_name, type_="unique")
        if not already_scoped:
            batch_op.create_unique_constraint(NEW_CONSTRAINT_NAME, new_columns)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "file"):
        return

    has_kb_id = _column_exists(bind, "file", "knowledge_base_id")
    scoped_columns = (
        ["user_id", "knowledge_base_id", "name"] if has_kb_id else ["user_id", "name"]
    )

    scoped_name = _unique_constraint_on(bind, "file", scoped_columns)
    legacy_already = _unique_constraint_on(bind, "file", ["name"])

    with op.batch_alter_table("file", schema=None) as batch_op:
        if scoped_name:
            batch_op.drop_constraint(scoped_name, type_="unique")
        # Restoring the global UNIQUE(name) may fail if rows accumulated after
        # the upgrade share a name across users/KBs. Operators must resolve
        # such duplicates manually before downgrading.
        if not legacy_already:
            batch_op.create_unique_constraint(LEGACY_CONSTRAINT_NAME, ["name"])
