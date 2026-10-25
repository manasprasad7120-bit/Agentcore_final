from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlmodel import Field, SQLModel


class PackageRequest(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "package_request"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    service_name: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    package_name: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    requested_version: str = Field(sa_column=Column(String(100), nullable=False))
    justification: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(sa_column=Column(String(20), nullable=False, index=True, default="PENDING"))

    requested_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    reviewed_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    deployed_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)

    review_comments: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    deployment_notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deployed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        Index("ix_package_request_service_status", "service_name", "status"),
        Index("ix_package_request_package_status", "package_name", "status"),
    )

