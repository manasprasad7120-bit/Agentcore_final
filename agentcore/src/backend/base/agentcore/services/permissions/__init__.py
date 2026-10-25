"""Permission scope helpers shared across Outlook, SharePoint, and Teams connectors."""

from agentcore.services.permissions.scope_check import (
    ConnectorPermissionError,
    graph_permission_error_message,
    has_any_scope,
    has_scope,
    is_graph_permission_error,
    parse_jwt_roles,
    parse_oauth_scopes,
    require_any_scope,
    require_scope,
)

__all__ = [
    "ConnectorPermissionError",
    "graph_permission_error_message",
    "has_any_scope",
    "has_scope",
    "is_graph_permission_error",
    "parse_jwt_roles",
    "parse_oauth_scopes",
    "require_any_scope",
    "require_scope",
]
