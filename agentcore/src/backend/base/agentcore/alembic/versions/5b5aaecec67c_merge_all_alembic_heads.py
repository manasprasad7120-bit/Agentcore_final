"""merge all alembic heads

Revision ID: 5b5aaecec67c
Revises: 20260316_moved_uat_prod, k1b2c3d4e5f7, u3v4w5x6y7z8
Create Date: 2026-03-17 14:56:19.992245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '5b5aaecec67c'
down_revision: Union[str, None] = ('20260316_moved_uat_prod', 'k1b2c3d4e5f7', 'u3v4w5x6y7z8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
