"""fix organization and department timestamp columns to use TIMESTAMPTZ

Revision ID: 20260626_fix_ts_tz
Revises: 20260511_guardrail_versioning
Create Date: 2026-06-26

asyncpg raises "can't subtract offset-naive and offset-aware datetimes" when
a timezone-aware datetime (produced by datetime.now(timezone.utc)) is inserted
into a TIMESTAMP WITHOUT TIME ZONE column. The organization and department
tables were created with bare TIMESTAMP columns; this migration converts them
to TIMESTAMPTZ so the columns accept tz-aware values. Existing rows are
reinterpreted as UTC (USING col AT TIME ZONE 'UTC'), which matches how the
application has always written them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_fix_ts_tz"
down_revision: Union[str, Sequence[str], None] = "20260511_guardrail_versioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organization "
        "ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE organization "
        "ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE department "
        "ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE department "
        "ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE organization "
        "ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE USING created_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE organization "
        "ALTER COLUMN updated_at TYPE TIMESTAMP WITHOUT TIME ZONE USING updated_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE department "
        "ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE USING created_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE department "
        "ALTER COLUMN updated_at TYPE TIMESTAMP WITHOUT TIME ZONE USING updated_at AT TIME ZONE 'UTC'"
    )
