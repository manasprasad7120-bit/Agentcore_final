"""merge all alembic heads

Revision ID: cfa14f7f9648
Revises: 9d2789fbd7a4, f1a2b3c4d5e8
Create Date: 2026-03-15 21:07:22.364514

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'cfa14f7f9648'
down_revision: Union[str, None] = ('9d2789fbd7a4', 'f1a2b3c4d5e8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
