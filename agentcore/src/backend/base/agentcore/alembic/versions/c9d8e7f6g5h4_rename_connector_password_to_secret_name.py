"""rename connector password_encrypted to password_secret_name

Revision ID: c9d8e7f6g5h4
Revises: 18d101d98961
Create Date: 2026-03-15 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = "c9d8e7f6g5h4"
down_revision: Union[str, None] = "18d101d98961"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = Inspector.from_engine(bind)
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade() -> None:
    bind = op.get_bind()
    if "connector_catalogue" not in Inspector.from_engine(bind).get_table_names():
        return

    with op.batch_alter_table("connector_catalogue", schema=None) as batch_op:
        if not _has_column(bind, "connector_catalogue", "password_secret_name"):
            batch_op.add_column(sa.Column("password_secret_name", sa.String(length=255), nullable=True))
        if _has_column(bind, "connector_catalogue", "password_encrypted"):
            batch_op.drop_column("password_encrypted")


def downgrade() -> None:
    bind = op.get_bind()
    if "connector_catalogue" not in Inspector.from_engine(bind).get_table_names():
        return

    with op.batch_alter_table("connector_catalogue", schema=None) as batch_op:
        if not _has_column(bind, "connector_catalogue", "password_encrypted"):
            batch_op.add_column(sa.Column("password_encrypted", sa.Text(), nullable=True))
        if _has_column(bind, "connector_catalogue", "password_secret_name"):
            batch_op.drop_column("password_secret_name")
