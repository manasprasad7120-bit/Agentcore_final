from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


class NotificationTypeEnum(str, Enum):
    WARNING = "warning"
    BREACH = "breach"


class CostLimitNotification(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "cost_limit_notification"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    cost_limit_id: UUID = Field(
        sa_column=Column(ForeignKey("cost_limit.id", ondelete="CASCADE"), nullable=False, index=True),
    )

    notification_type: str = Field(
        sa_column=Column(String(20), nullable=False),
    )

    period_start: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    period_end: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    cost_at_notification: float = Field(
        sa_column=Column(Numeric(12, 4), nullable=False),
    )
    limit_amount_usd: float = Field(
        sa_column=Column(Numeric(12, 4), nullable=False),
    )
    percentage_used: float = Field(
        sa_column=Column(Numeric(5, 2), nullable=False),
    )

    dismissed_by_user_ids: list[UUID] | None = Field(
        default_factory=list,
        sa_column=Column(ARRAY(PG_UUID(as_uuid=True)), nullable=True, server_default="{}"),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint(
            "cost_limit_id",
            "notification_type",
            "period_start",
            name="uq_cost_limit_notification_period",
        ),
    )
