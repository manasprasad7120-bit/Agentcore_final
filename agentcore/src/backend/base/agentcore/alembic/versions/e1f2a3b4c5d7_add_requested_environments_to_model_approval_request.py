"""add requested_environments to model_approval_request

Revision ID: e1f2a3b4c5d7
Revises: e0f1a2b3c4d6
Create Date: 2026-03-16 17:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d7"
down_revision: Union[str, None] = "e0f1a2b3c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_approval_request", sa.Column("requested_environments", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE model_approval_request "
        "SET requested_environments = json_build_array(target_environment) "
        "WHERE requested_environments IS NULL AND target_environment IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("model_approval_request", "requested_environments")
