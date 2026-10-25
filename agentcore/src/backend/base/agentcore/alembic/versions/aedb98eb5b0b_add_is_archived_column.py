"""add is_archived column

Revision ID: aedb98eb5b0b
Revises: c7d8e9f0a1b2
Create Date: 2026-04-07 00:58:12.056612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'aedb98eb5b0b'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('orch_conversation', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_archived',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('false')
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("orch_conversation", schema=None) as batch_op:
        batch_op.drop_column("is_archived")
