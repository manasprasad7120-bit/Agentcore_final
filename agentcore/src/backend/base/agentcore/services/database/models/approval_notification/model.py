from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class ApprovalNotification(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "approval_notification"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    recipient_user_id: UUID = Field(
        sa_column=Column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True),
    )
    entity_type: str = Field(sa_column=Column(String(32), nullable=False))
    entity_id: str = Field(sa_column=Column(String(64), nullable=False))
    title: str = Field(sa_column=Column(String(255), nullable=False))
    link: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    is_read: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false", index=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    read_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id",
            "entity_type",
            "entity_id",
            name="uq_approval_notification_recipient_entity",
        ),
        Index("ix_approval_notification_recipient_created", "recipient_user_id", "created_at"),
    )
