"""merge concurrent migrations

Revision ID: c4066ea5e11e
Revises: 944da930ac21, cl1a2b3c4d5e
Create Date: 2026-03-18 03:05:02.621866

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'c4066ea5e11e'
down_revision: Union[str, None] = ('944da930ac21', 'cl1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
