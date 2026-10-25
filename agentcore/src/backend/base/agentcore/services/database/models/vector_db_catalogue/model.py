from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class VectorDBCatalogue(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "vector_db_catalogue"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    provider: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    deployment: str = Field(sa_column=Column(String(50), nullable=False))
    dimensions: str = Field(sa_column=Column(String(50), nullable=False))
    index_type: str = Field(sa_column=Column(String(100), nullable=False))
    status: str = Field(sa_column=Column(String(50), nullable=False))
    vector_count: str = Field(sa_column=Column(String(50), nullable=False))
    is_custom: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))

    # Environment: uat / prod
    environment: str = Field(default="uat", sa_column=Column(String(10), nullable=True, index=True))

    # Pinecone-specific tracking
    index_name: str | None = Field(default=None, sa_column=Column(String(256), nullable=True))
    namespace: str | None = Field(default=None, sa_column=Column(String(256), nullable=True))

    # Agent association
    agent_id: UUID | None = Field(default=None, sa_column=Column("agent_id", sa.Uuid(), nullable=True, index=True))
    agent_name: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))

    # UAT → PROD lineage
    source_entry_id: UUID | None = Field(
        default=None,
        sa_column=Column("source_entry_id", sa.Uuid(), ForeignKey("vector_db_catalogue.id"), nullable=True),
    )

    # Migration tracking
    migration_status: str | None = Field(default=None, sa_column=Column(String(50), nullable=True))
    migrated_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    vectors_copied: int | None = Field(default=0, sa_column=Column(Integer, nullable=True))

    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    published_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    published_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    __table_args__ = (
        CheckConstraint("(dept_id IS NULL) OR (org_id IS NOT NULL)", name="ck_vector_db_scope_consistency"),
        ForeignKeyConstraint(
            ["org_id", "dept_id"],
            ["department.org_id", "department.id"],
            name="fk_vector_db_org_dept_department",
        ),
        UniqueConstraint("org_id", "dept_id", "name", name="uq_vector_db_catalogue_scope_name"),
        Index("ix_vector_db_catalogue_org_dept", "org_id", "dept_id"),
    )
