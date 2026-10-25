"""merge all heads

Revision ID: 830fc4fdcd13
Revises: 20260317_merge_all, 5b5aaecec67c, b1c2d3e4f5g6
Create Date: 2026-03-17 20:42:34.497580

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '830fc4fdcd13'
down_revision: Union[str, None] = ('20260317_merge_all', '5b5aaecec67c', 'b1c2d3e4f5g6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
