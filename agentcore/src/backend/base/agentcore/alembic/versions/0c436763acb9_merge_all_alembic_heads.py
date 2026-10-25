"""merge all alembic heads

Revision ID: 0c436763acb9
Revises: ltm001_summarized_at, 20260322_user_expires, le1a2d3e4r6
Create Date: 2026-03-23 12:03:56.703996

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '0c436763acb9'
down_revision: Union[str, None] = ('ltm001_summarized_at', '20260322_user_expires', 'le1a2d3e4r6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
