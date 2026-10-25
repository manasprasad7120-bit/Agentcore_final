"""merge heads

Revision ID: 354596a8b250
Revises: d2c10200ff01, v9w0x1y2z3a4
Create Date: 2026-03-12 20:37:38.743632

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '354596a8b250'
down_revision: Union[str, None] = ('d2c10200ff01', 'v9w0x1y2z3a4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
