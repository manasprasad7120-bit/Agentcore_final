from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import String
from sqlmodel import Field, SQLModel, Column, JSON


class DatasetItemBase(SQLModel):
    input: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    expected_output: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    metadata_: Optional[dict] = Field(default=None, sa_column=Column("metadata", JSON, nullable=True))
    source_trace_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    source_observation_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    status: str = Field(default="ACTIVE", sa_column=Column(String(20), nullable=False, default="ACTIVE"))


class DatasetItem(DatasetItemBase, table=True):
    __tablename__ = "dataset_item"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    dataset_id: UUID = Field(foreign_key="dataset.id", index=True, nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_response(self, dataset_name: str = "") -> dict:
        return {
            "id": str(self.id),
            "dataset_name": dataset_name,
            "status": self.status,
            "input": self.input,
            "expected_output": self.expected_output,
            "metadata": self.metadata_,
            "source_trace_id": self.source_trace_id,
            "source_observation_id": self.source_observation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
