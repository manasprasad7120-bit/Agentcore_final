"""Static risk-rule advisor for MCP server configurations.

Pure, dependency-free rule checks. No subprocess, no network, no LLM. Used by
the approval-review screen and the Add/Request MCP modal to surface risky
configurations to admins *before* anything is spawned or stored.

This is decision support, not an enforcement boundary - the admin still makes
the final call. The actual technical control against shell injection lives in
the MCP microservice spawn pathway.
"""

from agentcore.services.mcp_security.risk_advisor import (
    Finding,
    RiskAnalysis,
    Severity,
    analyze,
)

__all__ = ["Finding", "RiskAnalysis", "Severity", "analyze"]
