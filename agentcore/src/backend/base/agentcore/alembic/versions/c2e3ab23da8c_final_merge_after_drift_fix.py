"""final merge after drift fix

Revision ID: c2e3ab23da8c
Revises: ds20260319001, s2u3v4w5x6y7
Create Date: 2026-03-19 11:17:59.695790

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'c2e3ab23da8c'
down_revision: Union[str, None] = ('ds20260319001', 's2u3v4w5x6y7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
