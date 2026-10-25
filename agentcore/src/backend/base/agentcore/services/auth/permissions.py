from collections.abc import Awaitable, Callable
from typing import Any, List, Dict, Optional

from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from agentcore.services.settings.service import SettingsService
from agentcore.services.cache.redis_client import get_redis_client, reset_redis_client
from agentcore.services.deps import session_scope
from agentcore.services.database.models.role import Role
from agentcore.services.database.models.permission import Permission
from agentcore.services.database.models.role_permission import RolePermission
from sqlmodel import select, text


ROLE_ALIASES: dict[str, str] = {}

PERMISSION_ALIASES = {
    # Keep old permission checks working while roles move to assets-based keys.
    "view_project_page": ["view_projects_page"],
    "view_projects_page": ["view_project_page"],
    "view_assets_files_tab": ["view_files_tab"],
    "manage_users": ["view_admin_page"],
    "manage_roles": ["view_access_control_page"],
    "interact_agents": ["view_orchastration_page"],
    "view_orchestrator_page": ["view_orchastration_page"],
    "view_traces": ["view_observability_page"],
    "view_evaluation": ["view_evaluation_page"],
    "view_guardrails": ["view_guardrail_page"],
    "add_guardrails": ["add_guardrail"],
    "add_guardrail": ["add_guardrails"],
    "retire_guardrails": ["delete_guardrails", "retire_guardrail"],
    "delete_guardrails": ["retire_guardrails", "retire_guardrail"],
    "retire_guardrail": ["retire_guardrails", "delete_guardrails"],
    "view_vector_db": ["view_vectordb_page"],
    "view_vectorDb_page": ["view_vectordb_page"],
    # Keep MCP page access separate from Review & Approval's view_mcp permission.
    "add_mcp": ["add_new_mcp"],
    "edit_mcp": ["edit_mcp_registry", "edit_mcp_server"],
    "edit_mcp_registry": ["edit_mcp", "edit_mcp_server"],
    "delete_mcp": ["delete_mcp_registry", "delete_mcp_server", "retire_mcp"],
    "delete_mcp_registry": ["delete_mcp", "delete_mcp_server", "retire_mcp"],
    "retire_mcp": ["delete_mcp", "delete_mcp_registry", "delete_mcp_server"],
    "view_knowledge_base_management": ["view_knowledge_base"],
    "view_approval_page": ["approve_reject_page", "view_hitl_approvals_page"],
    "view_control_panel": ["view_agent_scheduler_page"],
    "view_agent_scheduler_page": ["view_control_panel"],
    "add_scheduler": ["start_stop_agent"],
    "view_model_catalogue_page": ["view_models"],
    "view_agent_catalogue_page": ["view_published_agents"],
    "view_mcp_servers_page": ["view_mcp_page"],
    "view_guardrails_page": ["view_guardrail_page"],
    "view_vector_db_page": ["view_vectordb_page"],
    "delete_vector_db_catalogue": ["retire_vector_db"],
    "retire_vector_db": ["delete_vector_db_catalogue"],
    "view_observability_dashboard": ["view_observability_page"],
    "edit_project": ["edit_projects_page"],
    "edit_projects_page": ["edit_project"],
    "view_registry_agent": ["view_only_agent"],
    "view_only_agent": ["view_registry_agent"],
    "connectore_page": ["view_connectors_page", "connector_page"],
    "view_connectors_page": ["connectore_page", "connector_page"],
    "connector_page": ["connectore_page", "view_connectors_page"],
    "view_connector_page": ["connectore_page", "view_connectors_page", "connector_page"],
    "edit_model": ["edit_model_registry"],
    "edit_model_registry": ["edit_model"],
    "delete_model": ["delete_model_registry"],
    "delete_model_registry": ["delete_model"],
}


def _normalize_role(role: str) -> str:
    normalized = role.strip().lower().replace(" ", "_").replace("-", "_")
    return ROLE_ALIASES.get(normalized, normalized)


def normalize_role(role: str) -> str:
    return _normalize_role(role)


def _expand_permissions(perms: List[str]) -> List[str]:
    expanded: list[str] = []
    for perm in perms:
        if perm not in expanded:
            expanded.append(perm)
        for alias in PERMISSION_ALIASES.get(perm, []):
            if alias not in expanded:
                expanded.append(alias)
    return expanded


ACTIONS = {
    "VIEW_DASHBOARD": "view_dashboard",
    "MANAGE_USERS": "view_admin_page",
    "EDIT_AGENTS": "edit_agents",
    "VIEW_COSTS": "view_costs",
    "VIEW_FILES_TAB": "view_files_tab",
    "VIEW_ADMIN_PAGE": "view_admin_page",
    "VIEW_ACCESS_CONTROL_PAGE": "view_access_control_page",
    "MANAGE_ROLES": "view_access_control_page",
    "VIEW_AGENTS_PAGE": "view_agents_page",
    "VIEW_COMPONENTS_PAGE": "view_components_page",
    "VIEW_ASSETS_FILES_TAB": "view_assets_files_tab",
    "VIEW_ASSETS_KNOWLEDGE_TAB": "view_assets_knowledge_tab",
    "VIEW_SETTINGS_PAGE": "view_settings_page",
    "VIEW_SETTINGS_GLOBAL_VARIABLES_TAB": "view_settings_global_variables_tab",
    "VIEW_SETTINGS_API_KEYS_TAB": "view_settings_api_keys_tab",
    "VIEW_SETTINGS_SHORTCUTS_TAB": "view_settings_shortcuts_tab",
    "VIEW_SETTINGS_MESSAGES_TAB": "view_settings_messages_tab",
    "VIEW_MCP_SERVERS_PAGE": "view_mcp_page",
    "EDIT_MCP_REGISTRY": "edit_mcp",
    "DELETE_MCP_REGISTRY": "delete_mcp",
    "VIEW_MODEL_CATALOGUE_PAGE": "view_model_catalogue_page",
    "VIEW_AGENT_CATALOGUE_PAGE": "view_agent_catalogue_page",
    "VIEW_ORCHESTRATOR_PAGE": "view_orchastration_page",
    "VIEW_GUARDRAILS_PAGE": "view_guardrail_page",
    "ADD_GUARDRAILS": "add_guardrails",
    "RETIRE_GUARDRAILS": "retire_guardrails",
    "VIEW_VECTOR_DB_PAGE": "view_vectordb_page",
    "DELETE_VECTOR_DB_CATALOGUE": "delete_vector_db_catalogue",
    "VIEW_RELEASE_MANAGEMENT_PAGE": "view_release_management_page",
    "PUBLISH_RELEASE": "publish_release",
    "REQUEST_PACKAGES": "request_packages",
    "VIEW_REVIEW_AGENT_TAB": "view_agent",
    "VIEW_REVIEW_MODEL_TAB": "view_model",
    "VIEW_REVIEW_MCP_TAB": "view_mcp",
    "VIEW_OBSERVABILITY_DASHBOARD": "view_observability_page",
    "VIEW_EVALUATION_PAGE": "view_evaluation_page",
    "VIEW_APPROVAL_PAGE": "view_approval_page",
    "VIEW_HITL_APPROVALS_PAGE": "view_hitl_approvals_page",
    "HITL_APPROVE": "hitl_approve",
    "HITL_REJECT": "hitl_reject",
    "VIEW_AGENT_SCHEDULER_PAGE": "view_agent_scheduler_page",
    "MOVE_UAT_TO_PROD": "move_uat_to_prod",
    "VIEW_TIMEOUT_SETTINGS_PAGE": "view_timeout_settings_page",
    "VIEW_WORKAGENTS_PAGE": "view_workflows_page",
    "VIEW_PLAYGROUND_PAGE": "view_playground_page",
    "VIEW_AGENT_EDITOR": "view_agent_editor",
    "CONNECTORE_PAGE": "view_connector_page",
    "ADD_CONNECTOR": "add_connector",
    "EDIT_MODEL_REGISTRY": "edit_model",
    "DELETE_MODEL_REGISTRY": "delete_model",
}

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "root": [
        "view_dashboard",
        "view_projects_page",
        "edit_project",
        "delete_project",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_registry_agent",
        "view_models",
        "add_new_model",
        "retire_model",
        "edit_model",
        "delete_model",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "move_uat_to_prod",
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
        "edit_mcp",
        "delete_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "view_release_management_page",
        "publish_release",
        "view_help_support_page",
        "add_faq",
        "view_admin_page",
        "view_access_control_page",
        "view_connector_page",
        "add_connector",
        "view_hitl_approvals_page",
        "hitl_approve",
        "hitl_reject",
    ],
    "leader_executive": [
        "view_dashboard",
    ],
    "super_admin": [
        "view_dashboard",
        "view_projects_page",
        "edit_project",
        "delete_project",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_registry_agent",
        "view_models",
        "add_new_model",
        "retire_model",
        "edit_model",
        "delete_model",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "move_uat_to_prod",
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
        "edit_mcp",
        "delete_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "request_packages",
        "view_release_management_page",
        "view_help_support_page",
        "add_faq",
        "view_admin_page",
        "view_connector_page",
        "add_connector",
        "view_hitl_approvals_page",
        "hitl_approve",
        "hitl_reject",
    ],
    "department_admin": [
        "view_dashboard",
        "view_projects_page",
        "edit_project",
        "delete_project",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_registry_agent",
        "view_models",
        "add_new_model",
        "retire_model",
        "edit_model",
        "delete_model",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "move_uat_to_prod",
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
        "edit_mcp",
        "delete_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_packages_page",
        "request_packages",
        "view_release_management_page",
        "view_help_support_page",
        "add_faq",
        "view_admin_page",
        "view_connector_page",
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
        "view_registry_agent",
        "view_models",
        "request_new_model",
        "view_control_panel",
        "start_stop_agent",
        "move_uat_to_prod",
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
        "view_connector_page",
        "add_connector",
        "view_hitl_approvals_page",
    ],
    "business_user": [
        "view_dashboard",
        "view_projects_page",
        "view_published_agents",
        "copy_agents",
        "view_registry_agent",
        "view_models",
        "request_new_model",
        "view_control_panel",
        "start_stop_agent",
        "move_uat_to_prod",
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
        "view_connector_page",
        "add_connector",
        "view_hitl_approvals_page",
    ],
    "consumer": [
        "view_published_agents",
        "view_registry_agent",
        "view_orchastration_page",
        "interact_agents",
    ],
}

PERMISSION_VERSION = "v22"  # bump when permissions change


class PermissionCacheService:
    def __init__(self, settings_service: SettingsService):
        self.settings_service = settings_service
        self.redis = get_redis_client(settings_service)
        self.ttl = settings_service.settings.redis_cache_expire

    async def _redis_call_with_reconnect(
        self,
        *,
        action: str,
        key: str,
        call: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        try:
            return await call(self.redis)
        except (RedisConnectionError, RedisTimeoutError, RedisError, OSError) as exc:
            logger.warning(
                f"RBAC cache {action} failed for {key}: {exc}. "
                "Resetting Redis client and retrying once."
            )
            await reset_redis_client()
            self.redis = get_redis_client(self.settings_service)
            return await call(self.redis)

    async def get_permissions_for_role(self, role: str) -> List[str]:
        role = _normalize_role(role)
        if role == "root":
            async with session_scope() as session:
                all_perm_rows = (await session.exec(select(Permission.key))).all()
            db_keys = [p for p in all_perm_rows if p]
            default_keys = ROLE_PERMISSIONS.get("root", [])
            merged = list(dict.fromkeys([*db_keys, *default_keys]))
            return _expand_permissions(merged)

        key = f"role:{PERMISSION_VERSION}:{role}"

        cached = await self._redis_call_with_reconnect(
            action="read",
            key=key,
            call=lambda client: client.get(key),
        )
        if cached:
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")
            cached = str(cached)
            if cached == "__none__":
                return []
            if cached.strip():
                perms = _expand_permissions(cached.split(","))
                if perms != [""]:
                    return perms

        perms = await _get_permissions_for_role_db(role)
        if not perms:
            try:
                await self._redis_call_with_reconnect(
                    action="write",
                    key=key,
                    call=lambda client: client.set(key, "__none__", ex=self.ttl),
                )
                logger.info(f"RBAC cache write: {key} = []")
            except Exception as exc:
                logger.warning(f"RBAC cache write failed for {key}: {exc}")
            return []

        perms = _expand_permissions(perms)
        try:
            await self._redis_call_with_reconnect(
                action="write",
                key=key,
                call=lambda client: client.set(key, ",".join(perms), ex=self.ttl),
            )
            logger.info(f"RBAC cache write: {key} = {perms}")
        except Exception as exc:
            logger.warning(f"RBAC cache write failed for {key}: {exc}")
        return perms


permission_cache: Optional[PermissionCacheService] = None


async def get_permissions_for_role(role: str) -> List[str]:
    normalized = _normalize_role(role)
    if normalized == "root":
        async with session_scope() as session:
            all_perm_rows = (await session.exec(select(Permission.key))).all()
        # Root is system-managed: include DB keys plus current runtime defaults.
        db_keys = [p for p in all_perm_rows if p]
        default_keys = ROLE_PERMISSIONS.get("root", [])
        merged = list(dict.fromkeys([*db_keys, *default_keys]))
        return _expand_permissions(merged)

    global permission_cache
    if permission_cache is None:
        from agentcore.services.deps import get_settings_service

        permission_cache = PermissionCacheService(get_settings_service())

    perms = await permission_cache.get_permissions_for_role(role)
    if perms:
        return _expand_permissions(perms)
    return []


async def _get_permissions_for_role_db(role: str) -> List[str]:
    role = _normalize_role(role)
    async with session_scope() as session:
        role_row = (await session.exec(select(Role).where(Role.name == role))).first()
        if not role_row:
            return []
        stmt = (
            select(Permission.key)
            .select_from(RolePermission)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_row.id)
        )
        permissions = (await session.exec(stmt)).all()
        if permissions:
            return list(permissions)

        # Raw SQL fallback (avoids ORM/table name edge cases)
        try:
            return await get_permissions_for_role_session(session, role)
        except Exception:
            return []


async def get_permissions_for_role_session(session, role: str) -> List[str]:
    role = _normalize_role(role)
    raw = await session.exec(
        text(
            "SELECT p.key FROM role_permission rp "
            "JOIN permission p ON p.id = rp.permission_id "
            "JOIN role r ON r.id = rp.role_id "
            "WHERE r.name = :role_name"
        ),
        {"role_name": role},
    )
    return list(raw.all())


async def invalidate_role_permissions_cache(role: str) -> None:
    if not permission_cache:
        return
    role = _normalize_role(role)
    key = f"role:{PERMISSION_VERSION}:{role}"
    try:
        await permission_cache.redis.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to invalidate permission cache for {role}: {exc}")
