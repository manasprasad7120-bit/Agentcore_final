"""Add performance indexes for delete/permission hot paths

Adds missing indexes that cause full table scans on every user delete,
permission check, and membership lookup:

  - user_department_membership(user_id, status)  composite — every permission check
  - user_department_membership(department_id, status) composite — member existence checks
  - user_organization_membership(user_id, status) composite — org-wide permission checks
  - user_organization_membership(org_id, status)  composite — org-wide member checks
  - file(user_id)                  — DELETE by user was a full scan
  - user(created_by)               — UPDATE WHERE created_by = ? was a full scan
  - user(department_admin)         — UPDATE WHERE department_admin = ? was a full scan
  - user(deleted_at)               — WHERE deleted_at IS NULL was a full scan
  - approval_request(agent_id)     — DELETE WHERE agent_id IN (...) was a full scan
  - department(created_by)         — UPDATE WHERE created_by = ? was a full scan
  - organization(owner_user_id)    — UPDATE WHERE owner_user_id = ? was a full scan
  - organization(created_by)       — UPDATE WHERE created_by = ? was a full scan

Revision ID: lc2m3n4o5p6q
Revises: kb1m2n3o4p5q
Create Date: 2026-05-03
"""

from __future__ import annotations
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "lc2m3n4o5p6q"
down_revision: Union[str, Sequence[str], None] = "kb1m2n3o4p5q"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    return index_name in {
        idx["name"] for idx in sa.inspect(bind).get_indexes(table_name)
    }


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    # --- user_department_membership ---
    if _table_exists(bind, "user_department_membership"):
        if not _index_exists(bind, "user_department_membership", "ix_udm_user_status"):
            op.create_index("ix_udm_user_status", "user_department_membership", ["user_id", "status"])
        if not _index_exists(bind, "user_department_membership", "ix_udm_dept_status"):
            op.create_index("ix_udm_dept_status", "user_department_membership", ["department_id", "status"])

    # --- user_organization_membership ---
    if _table_exists(bind, "user_organization_membership"):
        if not _index_exists(bind, "user_organization_membership", "ix_uom_user_status"):
            op.create_index("ix_uom_user_status", "user_organization_membership", ["user_id", "status"])
        if not _index_exists(bind, "user_organization_membership", "ix_uom_org_status"):
            op.create_index("ix_uom_org_status", "user_organization_membership", ["org_id", "status"])

    # --- file ---
    if _table_exists(bind, "file"):
        if not _index_exists(bind, "file", "ix_file_user_id"):
            op.create_index("ix_file_user_id", "file", ["user_id"])

    # --- user ---
    if _table_exists(bind, "user"):
        if not _index_exists(bind, "user", "ix_user_created_by"):
            op.create_index("ix_user_created_by", "user", ["created_by"])
        if not _index_exists(bind, "user", "ix_user_department_admin"):
            op.create_index("ix_user_department_admin", "user", ["department_admin"])
        if not _index_exists(bind, "user", "ix_user_deleted_at"):
            op.create_index("ix_user_deleted_at", "user", ["deleted_at"])

    # --- approval_request ---
    if _table_exists(bind, "approval_request"):
        if not _index_exists(bind, "approval_request", "ix_approval_agent_id"):
            op.create_index("ix_approval_agent_id", "approval_request", ["agent_id"])

    # --- department ---
    if _table_exists(bind, "department"):
        if not _index_exists(bind, "department", "ix_department_created_by"):
            op.create_index("ix_department_created_by", "department", ["created_by"])

    # --- organization ---
    if _table_exists(bind, "organization"):
        if not _index_exists(bind, "organization", "ix_organization_owner_user_id"):
            op.create_index("ix_organization_owner_user_id", "organization", ["owner_user_id"])
        if not _index_exists(bind, "organization", "ix_organization_created_by"):
            op.create_index("ix_organization_created_by", "organization", ["created_by"])


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "organization"):
        if _index_exists(bind, "organization", "ix_organization_created_by"):
            op.drop_index("ix_organization_created_by", table_name="organization")
        if _index_exists(bind, "organization", "ix_organization_owner_user_id"):
            op.drop_index("ix_organization_owner_user_id", table_name="organization")

    if _table_exists(bind, "department"):
        if _index_exists(bind, "department", "ix_department_created_by"):
            op.drop_index("ix_department_created_by", table_name="department")

    if _table_exists(bind, "approval_request"):
        if _index_exists(bind, "approval_request", "ix_approval_agent_id"):
            op.drop_index("ix_approval_agent_id", table_name="approval_request")

    if _table_exists(bind, "user"):
        if _index_exists(bind, "user", "ix_user_deleted_at"):
            op.drop_index("ix_user_deleted_at", table_name="user")
        if _index_exists(bind, "user", "ix_user_department_admin"):
            op.drop_index("ix_user_department_admin", table_name="user")
        if _index_exists(bind, "user", "ix_user_created_by"):
            op.drop_index("ix_user_created_by", table_name="user")

    if _table_exists(bind, "file"):
        if _index_exists(bind, "file", "ix_file_user_id"):
            op.drop_index("ix_file_user_id", table_name="file")

    if _table_exists(bind, "user_organization_membership"):
        if _index_exists(bind, "user_organization_membership", "ix_uom_org_status"):
            op.drop_index("ix_uom_org_status", table_name="user_organization_membership")
        if _index_exists(bind, "user_organization_membership", "ix_uom_user_status"):
            op.drop_index("ix_uom_user_status", table_name="user_organization_membership")

    if _table_exists(bind, "user_department_membership"):
        if _index_exists(bind, "user_department_membership", "ix_udm_dept_status"):
            op.drop_index("ix_udm_dept_status", table_name="user_department_membership")
        if _index_exists(bind, "user_department_membership", "ix_udm_user_status"):
            op.drop_index("ix_udm_user_status", table_name="user_department_membership")
