"""merge remaining heads

Revision ID: 944da930ac21
Revises: t1a2g3s4y5s6, 830fc4fdcd13
Create Date: 2026-03-18 00:46:29.390056

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '944da930ac21'
down_revision: Union[str, None] = ('t1a2g3s4y5s6', '830fc4fdcd13')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
