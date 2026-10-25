"""add promoted_by foreign key to guardrail_catalogue

Adds the missing foreign key constraint on guardrail_catalogue.promoted_by
referencing user.id.

Revision ID: gc7f8e9d0a1b2
Revises: 354596a8b250
Create Date: 2026-03-13 15:30:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "gc7f8e9d0a1b2"
down_revision: Union[str, Sequence[str], None] = "354596a8b250"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if not _has_fk(bind, "guardrail_catalogue", "fk_guardrail_catalogue_promoted_by_user"):
        op.create_foreign_key(
            "fk_guardrail_catalogue_promoted_by_user",
            "guardrail_catalogue",
            "user",
            ["promoted_by"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if _has_fk(bind, "guardrail_catalogue", "fk_guardrail_catalogue_promoted_by_user"):
        op.drop_constraint(
            "fk_guardrail_catalogue_promoted_by_user",
            "guardrail_catalogue",
            type_="foreignkey",
        )

