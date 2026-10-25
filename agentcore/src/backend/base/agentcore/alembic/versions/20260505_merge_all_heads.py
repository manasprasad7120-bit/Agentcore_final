"""merge all alembic heads

Revision ID: 20260505_merge_all
Revises: 20260504_password_reset_token, 20260505_adp_add_dept_ids, lc2m3n4o5p6q
Create Date: 2026-05-05
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence


revision: str = "20260505_merge_all"
down_revision: tuple[str, ...] = (
    "20260504_password_reset_token",
    "20260505_adp_add_dept_ids",
    "lc2m3n4o5p6q",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
