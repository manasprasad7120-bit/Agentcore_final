"""merge heads

Revision ID: 9d2789fbd7a4
Revises: c9d8e7f6g5h4, f1a2b3c4d5e7
Create Date: 2026-03-15 20:13:23.667617

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '9d2789fbd7a4'
down_revision: Union[str, None] = ('c9d8e7f6g5h4', 'f1a2b3c4d5e7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
