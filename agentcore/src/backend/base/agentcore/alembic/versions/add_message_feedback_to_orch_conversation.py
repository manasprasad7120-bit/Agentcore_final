"""add message feedback columns to orch_conversation

Adds four nullable columns to the orch_conversation table so each assistant
message can carry a single thumbs up/down feedback from the user (MiBuddy-parity
— one feedback per message, upserted on re-vote, nulled out on un-vote):

  - feedback_rating   str   "up" | "down" | NULL
  - feedback_reasons  JSON  array of reason chip labels (e.g. ["Correct"])
  - feedback_comment  Text  optional free-text feedback (≤300 chars)
  - feedback_at       datetime timestamp of the most recent rating

All columns are nullable; existing rows receive NULL (no backfill needed).

Revision ID: fb1k2m3n4o5p
Revises: 95791a21c989
Create Date: 2026-04-21 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fb1k2m3n4o5p"
down_revision: Union[str, None] = "95791a21c989"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orch_conversation", schema=None) as batch_op:
        batch_op.add_column(sa.Column("feedback_rating", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("feedback_reasons", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("feedback_comment", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("feedback_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orch_conversation", schema=None) as batch_op:
        batch_op.drop_column("feedback_at")
        batch_op.drop_column("feedback_comment")
        batch_op.drop_column("feedback_reasons")
        batch_op.drop_column("feedback_rating")
