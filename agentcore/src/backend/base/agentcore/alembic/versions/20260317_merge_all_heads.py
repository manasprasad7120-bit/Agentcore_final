"""merge all alembic heads

Revision ID: 20260317_merge_all
Revises: 20260317_agent_api_key, cfa14f7f9648, u3v4w5x6y7z8
Create Date: 2026-03-17 12:15:00.000000
"""

from __future__ import annotations
from typing import Union

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "20260317_merge_all"
down_revision: tuple[str, ...] = ("20260317_agent_api_key", "cfa14f7f9648", "u3v4w5x6y7z8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

