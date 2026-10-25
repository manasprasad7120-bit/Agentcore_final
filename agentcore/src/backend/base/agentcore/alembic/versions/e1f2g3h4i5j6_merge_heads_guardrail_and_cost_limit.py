"""merge heads g3e1x0l9a7b2 and cl2a3b4c5d6e

Revision ID: e1f2g3h4i5j6
Revises: g3e1x0l9a7b2, cl2a3b4c5d6e
Create Date: 2026-03-18
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "e1f2g3h4i5j6"
down_revision: str | Sequence[str] | None = ("g3e1x0l9a7b2", "cl2a3b4c5d6e")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
