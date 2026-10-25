from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel, Column, JSON


class DatasetBase(SQLModel):
    name: str = Field(sa_column=Column(String(200), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    metadata_: Optional[dict] = Field(default=None, sa_column=Column("metadata", JSON, nullable=True))
    visibility: str = Field(
        default="private",
        sa_column=Column(String(20), nullable=False, default="private"),
    )
    public_scope: Optional[str] = Field(default=None, sa_column=Column(String(20), nullable=True))
    public_dept_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))


class Dataset(DatasetBase, table=True):
    __tablename__ = "dataset"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_dataset_user_name"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True, nullable=False)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", index=True, nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", index=True, nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_response(self, *, item_count: int = 0, created_by: str | None = None) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata_,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "item_count": item_count,
            "visibility": self.visibility or "private",
            "public_scope": self.public_scope,
            "owner_user_id": str(self.user_id),
            "created_by": created_by,
            "created_by_id": str(self.user_id),
            "org_id": str(self.org_id) if self.org_id else None,
            "dept_id": str(self.dept_id) if self.dept_id else None,
            "public_dept_ids": self.public_dept_ids,
        }
