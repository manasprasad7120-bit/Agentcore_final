from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, Index, String, text
from sqlmodel import Field, SQLModel


class GuardrailExecutionLog(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "guardrail_execution_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    guardrail_id: str = Field(
        default="",
        sa_column=Column(String(80), nullable=False, server_default=text("''")),
    )
    agent_id: UUID | None = Field(default=None, foreign_key="agent.id", nullable=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    user_id: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    session_id: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    action: str = Field(
        default="passthrough",
        sa_column=Column(String(30), nullable=False, server_default=text("'passthrough'")),
    )
    is_violation: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    environment: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )

    __table_args__ = (
        Index("ix_gel_org_id", "org_id"),
        Index("ix_gel_org_violation", "org_id", "is_violation"),
    )
