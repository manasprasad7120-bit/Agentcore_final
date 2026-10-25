# Path: src/backend/agentcore/services/database/models/agent_api_key/model.py

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Index, String, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.user.model import User


class AgentApiKeyBase(SQLModel):
    """Base model for agent API key records."""

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    deployment_id: UUID = Field(nullable=False, description="UAT or PROD deployment record ID")
    version: str = Field(
        max_length=10,
        nullable=False,
        sa_type=String(10),
        description="Deployment version string, e.g. 'v1', 'v2'",
    )
    environment: str = Field(
        max_length=4,
        nullable=False,
        sa_type=String(4),
        description="Deployment environment: 'uat' or 'prod'",
    )
    key_hash: str = Field(
        max_length=64,
        nullable=False,
        sa_type=String(64),
        description="SHA-256 hex digest of the plaintext API key",
    )
    key_prefix: str = Field(
        max_length=12,
        nullable=False,
        sa_type=String(12),
        description="First 8 chars of the plaintext key for UI display (e.g. agk_x7Gf)",
    )
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="Whether this key is active. Set False to revoke.",
    )
    created_by: UUID = Field(foreign_key="user.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_used_at: datetime | None = Field(
        default=None,
        nullable=True,
        description="Timestamp of last successful validation",
    )
    expires_at: datetime | None = Field(
        default=None,
        nullable=True,
        description="Optional expiry. Null means no expiry.",
    )


class AgentApiKey(AgentApiKeyBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "agent_api_key"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    agent: Optional["Agent"] = Relationship()
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentApiKey.created_by]"},
    )

    __table_args__ = (
        Index("ix_agent_api_key_hash", "key_hash"),
        Index("ix_agent_api_key_agent_env", "agent_id", "environment", "is_active"),
        Index("ix_agent_api_key_deployment", "deployment_id", "is_active"),
    )


class AgentApiKeyCreate(SQLModel):
    """Model for creating a new agent API key record."""

    agent_id: UUID
    deployment_id: UUID
    version: str
    environment: str
    key_hash: str
    key_prefix: str
    created_by: UUID
    is_active: bool = True
    expires_at: datetime | None = None


class AgentApiKeyRead(BaseModel):
    """Model for reading agent API key data (never includes full key)."""

    id: UUID
    agent_id: UUID
    deployment_id: UUID
    version: str
    environment: str
    key_prefix: str
    is_active: bool
    created_by: UUID
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
