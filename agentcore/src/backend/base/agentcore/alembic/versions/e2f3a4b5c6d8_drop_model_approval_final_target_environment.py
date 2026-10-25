"""drop final_target_environment from model_approval_request

Revision ID: e2f3a4b5c6d8
Revises: e1f2a3b4c5d7
Create Date: 2026-03-16 17:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d8"
down_revision: Union[str, None] = "e1f2a3b4c5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("model_approval_request", "final_target_environment")


def downgrade() -> None:
    op.add_column("model_approval_request", sa.Column("final_target_environment", sa.String(length=20), nullable=True))
