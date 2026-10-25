"""Create tag, project_tag, and agent_tag tables

Revision ID: t1a2g3s4y5s6
Revises: 20260317_add_agent_api_key_table
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "t1a2g3s4y5s6"
down_revision = None  # standalone; will be picked up by merge head
branch_labels = ("tags",)
depends_on = None


def upgrade() -> None:
    # ── tag ────────────────────────────────────────────────────────────
    op.create_table(
        "tag",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("category", sa.String(30), nullable=False, server_default="custom"),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("is_predefined", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_tag_org_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_tag_created_by"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "org_id", name="uq_tag_name_org"),
        if_not_exists=True,
    )
    op.create_index("ix_tag_name", "tag", ["name"], if_not_exists=True)
    op.create_index("ix_tag_org_id", "tag", ["org_id"], if_not_exists=True)
    op.create_index("ix_tag_category", "tag", ["category"], if_not_exists=True)

    # ── project_tag ───────────────────────────────────────────────────
    op.create_table(
        "project_tag",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], name="fk_project_tag_project_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], name="fk_project_tag_tag_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "tag_id"),
        if_not_exists=True,
    )
    op.create_index("ix_project_tag_project_id", "project_tag", ["project_id"], if_not_exists=True)
    op.create_index("ix_project_tag_tag_id", "project_tag", ["tag_id"], if_not_exists=True)

    # ── agent_tag ─────────────────────────────────────────────────────
    op.create_table(
        "agent_tag",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_agent_tag_agent_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], name="fk_agent_tag_tag_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "tag_id"),
        if_not_exists=True,
    )
    op.create_index("ix_agent_tag_agent_id", "agent_tag", ["agent_id"], if_not_exists=True)
    op.create_index("ix_agent_tag_tag_id", "agent_tag", ["tag_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_table("agent_tag")
    op.drop_table("project_tag")
    op.drop_table("tag")
