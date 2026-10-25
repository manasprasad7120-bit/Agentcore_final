"""merge all alembic heads

Revision ID: 18d101d98961
Revises: b3c4d5e6f7g8, gc7f8e9d0a1b2, pr1a2b3c4d5e
Create Date: 2026-03-14 16:51:40.514698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '18d101d98961'
down_revision: Union[str, None] = ('b3c4d5e6f7g8', 'gc7f8e9d0a1b2', 'pr1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
