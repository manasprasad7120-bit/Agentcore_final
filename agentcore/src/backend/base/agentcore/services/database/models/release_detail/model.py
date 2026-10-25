from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlmodel import Field, SQLModel


class ReleaseDetail(SQLModel, table=True):  # type: ignore[call-arg]
    """Structured rows attached to a release."""

    __tablename__ = "release_detail"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    release_id: UUID = Field(nullable=False, foreign_key="product_release.id", index=True)
    section_no: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    section_title: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    module: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    sub_module: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    feature_capability: str = Field(sa_column=Column(String(500), nullable=False))
    description_details: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    sort_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0, index=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
