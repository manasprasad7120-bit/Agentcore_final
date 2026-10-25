from datetime import datetime, timezone
from uuid import UUID, uuid4
from agentcore.schema.serialize import UUIDstr
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

class File(SQLModel, table=True):  # type: ignore[call-arg]
    # Uniqueness is scoped to (user, knowledge base, name) so different
    # users / KBs can hold files with the same name. The migration
    # 20260511_scope_file_name_unique_to_user_kb already established
    # this composite constraint at the DB level; declaring it here keeps
    # the ORM model in sync so alembic autogenerate stops detecting a
    # spurious diff on every startup.
    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_base_id", "name", name="uq_file_user_kb_name"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    knowledge_base_id: UUID | None = Field(default=None, foreign_key="knowledge_base.id", nullable=True, index=True)
    name: str = Field(nullable=False)
    path: str = Field(nullable=False)
    size: int = Field(nullable=False)
    provider: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
