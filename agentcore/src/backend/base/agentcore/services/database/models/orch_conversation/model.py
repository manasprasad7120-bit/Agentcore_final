# Path: src/backend/agentcore/services/database/models/orch_conversation/model.py
#
# Dedicated conversation table for Orchestrator Chat.
# Stores messages from multi-agent orchestrator sessions against UAT/PROD deployments.

import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import ConfigDict, field_serializer, field_validator
from sqlalchemy import ForeignKey as SAForeignKey, Index, Text, Uuid as SAUuid
from sqlmodel import JSON, Column, Field, SQLModel

from agentcore.schema.content_block import ContentBlock
from agentcore.schema.properties import Properties
from agentcore.schema.validators import str_to_naive_timestamp_validator


class OrchConversationBase(SQLModel):
    timestamp: Annotated[datetime, str_to_naive_timestamp_validator] = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    sender: str
    sender_name: str
    session_id: str
    text: str = Field(sa_column=Column(Text, nullable=False))
    files: list[str] = Field(default_factory=list)
    error: bool = Field(default=False)
    edit: bool = Field(default=False)

    properties: Properties = Field(default_factory=Properties)
    category: str = Field(default="message")
    content_blocks: list[ContentBlock] = Field(default_factory=list)

    @field_serializer("timestamp")
    def serialize_timestamp(self, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.replace(microsecond=0).isoformat()
        return value

    @field_validator("files", mode="before")
    @classmethod
    def validate_files(cls, value):
        if not value:
            value = []
        return value


class OrchConversationTable(OrchConversationBase, table=True):  # type: ignore[call-arg]
    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)
    __tablename__ = "orch_conversation"
    id: UUID = Field(default_factory=uuid4, primary_key=True)

    agent_id: UUID | None = Field(default=None)
    user_id: UUID | None = Field(default=None)
    org_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), SAForeignKey("organization.id", ondelete="SET NULL"), nullable=True),
    )
    dept_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), SAForeignKey("department.id", ondelete="SET NULL"), nullable=True),
    )
    deployment_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), nullable=True),
    )
    model_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), nullable=True),
    )
    reasoning_content: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    # Per-message thumbs up/down feedback (MiBuddy-parity).
    # One feedback per assistant message — clicking again clears these columns.
    # Migration: add_message_feedback_to_orch_conversation.
    feedback_rating: str | None = Field(default=None, nullable=True)  # "up" | "down" | None
    feedback_reasons: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    feedback_comment: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    feedback_at: datetime | None = Field(default=None, nullable=True)
    is_archived: bool = Field(default=False)
    # User-chosen title for the session (MiBuddy-parity rename). Stored on
    # any row of the session — the sessions-list query picks the first
    # non-null value. Migration: 95791a21c989_add_session_title_to_orch_conversation.
    session_title: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    ltm_summarized_at: datetime | None = Field(default=None, nullable=True)
    files: list[str] = Field(sa_column=Column(JSON))
    properties: dict | Properties = Field(default_factory=lambda: Properties().model_dump(), sa_column=Column(JSON))  # type: ignore[assignment]
    category: str = Field(sa_column=Column(Text))
    content_blocks: list[dict | ContentBlock] = Field(default_factory=list, sa_column=Column(JSON))  # type: ignore[assignment]

    __table_args__ = (
        Index("ix_orch_conversation_session", "session_id"),
        Index("ix_orch_conversation_agent", "agent_id"),
        Index("ix_orch_conversation_user", "user_id"),
        Index("ix_orch_conversation_org", "org_id"),
        Index("ix_orch_conversation_dept", "dept_id"),
        Index("ix_orch_conversation_deployment", "deployment_id"),
    )

    @field_validator("agent_id", "user_id", mode="before")
    @classmethod
    def validate_uuid_field(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = UUID(value)
        return value

    @field_validator("properties", "content_blocks", mode="before")
    @classmethod
    def validate_properties_or_content_blocks(cls, value):
        if isinstance(value, list):
            return [cls.validate_properties_or_content_blocks(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_serializer("properties", "content_blocks")
    @classmethod
    def serialize_properties_or_content_blocks(cls, value) -> dict | list[dict]:
        if isinstance(value, list):
            return [cls.serialize_properties_or_content_blocks(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, str):
            return json.loads(value)
        return value


class OrchConversationRead(OrchConversationBase):
    id: UUID
    agent_id: UUID | None = Field()
    user_id: UUID | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    deployment_id: UUID | None = None
    model_id: UUID | None = None
    reasoning_content: str | None = None
    feedback_rating: str | None = None
    feedback_reasons: list[str] | None = None
    feedback_comment: str | None = None
    feedback_at: datetime | None = None


class OrchConversationCreate(OrchConversationBase):
    agent_id: UUID | None = None
    user_id: UUID | None = None
    deployment_id: UUID | None = None


class OrchConversationUpdate(SQLModel):
    text: str | None = None
    sender: str | None = None
    sender_name: str | None = None
    session_id: str | None = None
    files: list[str] | None = None
    edit: bool | None = None
    error: bool | None = None
    properties: Properties | None = None
