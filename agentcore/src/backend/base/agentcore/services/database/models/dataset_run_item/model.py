from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import String
from sqlmodel import Field, SQLModel, Column, JSON


class DatasetRunItemBase(SQLModel):
    trace_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    observation_id: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    output: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    scores: Optional[List[dict]] = Field(default=None, sa_column=Column(JSON, nullable=True))


class DatasetRunItem(DatasetRunItemBase, table=True):
    __tablename__ = "dataset_run_item"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(foreign_key="dataset_run.id", index=True, nullable=False)
    dataset_item_id: UUID | None = Field(default=None, foreign_key="dataset_item.id", index=True, nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_response(self) -> dict:
        return {
            "id": str(self.id),
            "dataset_item_id": str(self.dataset_item_id) if self.dataset_item_id else None,
            "trace_id": self.trace_id,
            "observation_id": self.observation_id,
            "output": self.output,
            "scores": self.scores or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
