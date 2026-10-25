"""sync RBAC default role permissions with runtime matrix

Revision ID: rb1a2b3c4d5
Revises: r2s3t4u5v6w7
Create Date: 2026-03-18
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "rb1a2b3c4d5"
down_revision: str | Sequence[str] | None = "r2s3t4u5v6w7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "root": [
        "view_dashboard",
        "view_projects_page",
        "edit_projects_page",
        "delete_project",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_models",
        "add_new_model",
        "retire_model",
        "edit_model_registry",
        "delete_model_registry",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "add_scheduler",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "delete_vector_db_catalogue",
        "view_mcp_page",
        "add_new_mcp",
        "retire_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "view_release_management_page",
        "publish_release",
        "view_help_support_page",
        "add_faq",
        "view_admin_page",
        "view_access_control_page",
        "connectore_page",
        "add_connector",
        "view_hitl_approvals_page",
        "hitl_approve",
        "hitl_reject",
    ],
    "super_admin": [
        "view_dashboard",
        "view_projects_page",
        "edit_projects_page",
        "delete_project",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_models",
        "add_new_model",
        "retire_model",
        "edit_model_registry",
        "delete_model_registry",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "add_scheduler",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "delete_vector_db_catalogue",
        "view_mcp_page",
        "add_new_mcp",
        "retire_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "request_packages",
        "view_release_management_page",
        "view_help_support_page",
        "add_faq",
        "view_admin_page",
        "connectore_page",
        "add_connector",
        "view_hitl_approvals_page",
        "hitl_approve",
        "hitl_reject",
    ],
    "department_admin": [
        "view_dashboard",
        "view_projects_page",
        "edit_projects_page",
        "delete_project",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_models",
        "add_new_model",
        "retire_model",
        "edit_model_registry",
        "delete_model_registry",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "add_scheduler",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "delete_vector_db_catalogue",
        "view_mcp_page",
        "add_new_mcp",
        "retire_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "request_packages",
        "view_release_management_page",
        "view_help_support_page",
        "add_faq",
        "view_admin_page",
        "connectore_page",
        "add_connector",
        "view_hitl_approvals_page",
        "hitl_approve",
        "hitl_reject",
    ],
    "developer": [
        "view_dashboard",
        "view_projects_page",
        "view_published_agents",
        "copy_agents",
        "view_models",
        "request_new_model",
        "view_control_panel",
        "start_stop_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "view_mcp_page",
        "request_new_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "request_packages",
        "view_release_management_page",
        "view_help_support_page",
        "connectore_page",
        "add_connector",
        "view_hitl_approvals_page",
    ],
    "business_user": [
        "view_dashboard",
        "view_projects_page",
        "view_published_agents",
        "copy_agents",
        "view_models",
        "request_new_model",
        "view_control_panel",
        "start_stop_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "view_mcp_page",
        "request_new_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "request_packages",
        "view_release_management_page",
        "view_help_support_page",
        "connectore_page",
        "add_connector",
        "view_hitl_approvals_page",
    ],
    "consumer": [
        "view_published_agents",
        "view_only_agent",
        "view_orchastration_page",
        "interact_agents",
    ],
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    if not (_table_exists(bind, "permission") and _table_exists(bind, "role") and _table_exists(bind, "role_permission")):
        return

    role_names = list(DEFAULT_ROLE_PERMISSIONS.keys())
    permission_keys = sorted({key for keys in DEFAULT_ROLE_PERMISSIONS.values() for key in keys})

    # 1) Ensure permission rows exist
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")
    has_created_by = _has_column(bind, "permission", "created_by")
    has_updated_by = _has_column(bind, "permission", "updated_by")

    permission_rows = bind.execute(
        sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": permission_keys},
    ).fetchall()
    permission_id_by_key = {str(r[1]): str(r[0]) for r in permission_rows}

    for key in permission_keys:
        if key in permission_id_by_key:
            continue
        cols = ["id", "key", "name", "description"]
        vals = [":id", ":key", ":name", ":description"]
        params: dict[str, object] = {
            "id": str(uuid4()),
            "key": key,
            "name": key.replace("_", " "),
            "description": None,
            "category": "RBAC",
            "is_system": True,
            "created_by": None,
            "updated_by": None,
        }
        if has_category:
            cols.append("category")
            vals.append(":category")
        if has_is_system:
            cols.append("is_system")
            vals.append(":is_system")
        if has_created_by:
            cols.append("created_by")
            vals.append(":created_by")
        if has_updated_by:
            cols.append("updated_by")
            vals.append(":updated_by")
        if has_created_at:
            cols.append("created_at")
            vals.append("CURRENT_TIMESTAMP")
        if has_updated_at:
            cols.append("updated_at")
            vals.append("CURRENT_TIMESTAMP")

        bind.execute(
            sa.text(f"INSERT INTO permission ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
            params,
        )

    # Refresh permission ids after insert
    permission_rows = bind.execute(
        sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": permission_keys},
    ).fetchall()
    permission_id_by_key = {str(r[1]): str(r[0]) for r in permission_rows}

    # 2) Ensure default system roles exist
    has_display_name = _has_column(bind, "role", "display_name")
    has_is_active = _has_column(bind, "role", "is_active")
    has_role_created_at = _has_column(bind, "role", "created_at")
    has_role_updated_at = _has_column(bind, "role", "updated_at")
    has_role_created_by = _has_column(bind, "role", "created_by")
    has_role_updated_by = _has_column(bind, "role", "updated_by")

    role_rows = bind.execute(
        sa.text("SELECT id, name FROM role WHERE name IN :names").bindparams(sa.bindparam("names", expanding=True)),
        {"names": role_names},
    ).fetchall()
    role_id_by_name = {str(r[1]): str(r[0]) for r in role_rows}

    for role_name in role_names:
        if role_name in role_id_by_name:
            continue
        cols = ["id", "name", "description", "is_system"]
        vals = [":id", ":name", ":description", ":is_system"]
        params: dict[str, object] = {
            "id": str(uuid4()),
            "name": role_name,
            "display_name": role_name.replace("_", " ").title(),
            "description": f"System role: {role_name}",
            "is_system": True,
            "is_active": True,
            "created_by": None,
            "updated_by": None,
        }

        if has_display_name:
            cols.append("display_name")
            vals.append(":display_name")
        if has_is_active:
            cols.append("is_active")
            vals.append(":is_active")
        if has_role_created_by:
            cols.append("created_by")
            vals.append(":created_by")
        if has_role_updated_by:
            cols.append("updated_by")
            vals.append(":updated_by")
        if has_role_created_at:
            cols.append("created_at")
            vals.append("CURRENT_TIMESTAMP")
        if has_role_updated_at:
            cols.append("updated_at")
            vals.append("CURRENT_TIMESTAMP")

        bind.execute(
            sa.text(f"INSERT INTO role ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
            params,
        )

    role_rows = bind.execute(
        sa.text("SELECT id, name FROM role WHERE name IN :names").bindparams(sa.bindparam("names", expanding=True)),
        {"names": role_names},
    ).fetchall()
    role_id_by_name = {str(r[1]): str(r[0]) for r in role_rows}

    # 3) Sync role_permission rows to default matrix (same effect as Restore All Defaults)
    has_rp_created_at = _has_column(bind, "role_permission", "created_at")
    has_rp_updated_at = _has_column(bind, "role_permission", "updated_at")
    has_rp_created_by = _has_column(bind, "role_permission", "created_by")
    has_rp_updated_by = _has_column(bind, "role_permission", "updated_by")

    for role_name, keys in DEFAULT_ROLE_PERMISSIONS.items():
        role_id = role_id_by_name.get(role_name)
        if not role_id:
            continue

        bind.execute(sa.text("DELETE FROM role_permission WHERE role_id = :role_id"), {"role_id": role_id})

        for key in keys:
            permission_id = permission_id_by_key.get(key)
            if not permission_id:
                continue

            cols = ["id", "role_id", "permission_id"]
            vals = [":id", ":role_id", ":permission_id"]
            params: dict[str, object] = {
                "id": str(uuid4()),
                "role_id": role_id,
                "permission_id": permission_id,
                "created_by": None,
                "updated_by": None,
            }
            if has_rp_created_by:
                cols.append("created_by")
                vals.append(":created_by")
            if has_rp_updated_by:
                cols.append("updated_by")
                vals.append(":updated_by")
            if has_rp_created_at:
                cols.append("created_at")
                vals.append("CURRENT_TIMESTAMP")
            if has_rp_updated_at:
                cols.append("updated_at")
                vals.append("CURRENT_TIMESTAMP")

            bind.execute(
                sa.text(f"INSERT INTO role_permission ({', '.join(cols)}) VALUES ({', '.join(vals)})"),
                params,
            )


def downgrade() -> None:
    # Non-destructive: keep current role/permission mappings.
    return

