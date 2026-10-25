"""add environments array to model_registry

Revision ID: e0f1a2b3c4d6
Revises: cfa14f7f9648
Create Date: 2026-03-16 17:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d6"
down_revision: Union[str, None] = "cfa14f7f9648"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_registry", sa.Column("environments", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE model_registry "
        "SET environments = json_build_array(environment) "
        "WHERE environments IS NULL AND environment IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("model_registry", "environments")
