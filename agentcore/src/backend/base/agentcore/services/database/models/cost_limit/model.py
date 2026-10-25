from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel


class ScopeTypeEnum(str, Enum):
    ORGANIZATION = "organization"
    DEPARTMENT = "department"


class ActionOnBreachEnum(str, Enum):
    NOTIFY_ONLY = "notify_only"
    NOTIFY_AND_BLOCK = "notify_and_block"


class PeriodTypeEnum(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    CUSTOM = "custom"


class CostLimit(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "cost_limit"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    scope_type: str = Field(
        sa_column=Column(String(20), nullable=False),
    )
    org_id: UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)

    limit_amount_usd: float = Field(
        sa_column=Column(Numeric(12, 4), nullable=False),
    )
    currency: str = Field(
        default="USD",
        sa_column=Column(String(3), nullable=False, server_default=text("'USD'")),
    )
    period_type: str = Field(
        default="monthly",
        sa_column=Column(String(20), nullable=False, server_default=text("'monthly'")),
    )
    period_start_day: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    warning_threshold_pct: int = Field(
        default=80,
        sa_column=Column(Integer, nullable=False, server_default=text("80")),
    )
    action_on_breach: str = Field(
        default="notify_only",
        sa_column=Column(String(30), nullable=False, server_default=text("'notify_only'")),
    )

    is_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )

    last_checked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_breach_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_warning_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    current_period_cost_usd: float | None = Field(
        default=0,
        sa_column=Column(Numeric(12, 4), nullable=True, server_default=text("0")),
    )
    current_period_start: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    created_by: UUID = Field(foreign_key="user.id", nullable=False)
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("scope_type", "org_id", "dept_id", name="uq_cost_limit_scope"),
        CheckConstraint(
            "(scope_type = 'organization' AND dept_id IS NULL) OR "
            "(scope_type = 'department' AND dept_id IS NOT NULL)",
            name="chk_cost_limit_dept_requires_scope",
        ),
        CheckConstraint(
            "period_start_day BETWEEN 1 AND 28",
            name="chk_cost_limit_period_start_day",
        ),
        CheckConstraint(
            "warning_threshold_pct BETWEEN 1 AND 100",
            name="chk_cost_limit_warning_pct",
        ),
    )
