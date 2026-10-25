from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Column, Date, DateTime, Index, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Package(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "package"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    service_name: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    version: str = Field(sa_column=Column(String(100), nullable=False))
    version_spec: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    package_type: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    snapshot_id: str | None = Field(default=None, sa_column=Column(String(100), nullable=True, index=True))
    build_id: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    commit_sha: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    release_id: UUID | None = Field(default=None, nullable=True, foreign_key="product_release.id", index=True)
    required_by: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    required_by_details: list[dict[str, str]] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    start_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    end_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    source: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    synced_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        Index("ix_package_name_package_type_service", "name", "package_type", "service_name"),
    )


class ProductRelease(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "product_release"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    version: str = Field(sa_column=Column(String(50), nullable=False, unique=True, index=True))
    major: int = Field(nullable=False)
    minor: int = Field(nullable=False)
    patch: int = Field(nullable=False)
    release_notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    document_hash: str | None = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    document_file_name: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    document_storage_path: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    document_content_type: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    document_size: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    document_uploaded_by: UUID | None = Field(default=None, nullable=True, foreign_key="user.id", index=True)
    document_uploaded_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    start_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    end_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    created_by: UUID | None = Field(default=None, nullable=True, foreign_key="user.id", index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("major", "minor", "patch", name="uq_product_release_semver"),
    )
