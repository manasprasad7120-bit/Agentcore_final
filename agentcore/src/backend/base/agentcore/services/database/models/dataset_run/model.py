from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import String, Text
from sqlmodel import Field, SQLModel, Column, JSON


class DatasetRunBase(SQLModel):
    name: str = Field(sa_column=Column(String(200), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    metadata_: Optional[dict] = Field(default=None, sa_column=Column("metadata", JSON, nullable=True))


class DatasetRun(DatasetRunBase, table=True):
    __tablename__ = "dataset_run"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    dataset_id: UUID = Field(foreign_key="dataset.id", index=True, nullable=False)
    user_id: UUID | None = Field(default=None, foreign_key="user.id", index=True, nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_response(self, dataset_name: str = "") -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata_,
            "dataset_id": str(self.dataset_id),
            "dataset_name": dataset_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
