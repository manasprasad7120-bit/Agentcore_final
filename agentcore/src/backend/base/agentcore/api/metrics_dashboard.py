"""Metrics Dashboard API — reusable proxy for Prometheus + Grafana HTTP APIs
plus org/dept/user-scoped analytics endpoints.

Standalone router: any app can call these endpoints.
Read-only — no write operations on Prometheus or Grafana.

To remove this feature:
  1. Delete this file
  2. Remove 2 lines from router.py (import + include_router)
"""

import asyncio
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.permissions import normalize_role
from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.conversation.model import ConversationTable
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.project.model import Project
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.vertex_builds.model import VertexBuildTable
from agentcore.services.deps import get_session

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")
GRAFANA_API_KEY = os.getenv("GRAFANA_API_KEY", "")

# Azure Managed Prometheus settings (optional)
# Preferred: set only RESOURCE_ID — auth via AKS Managed Identity (DefaultAzureCredential).
# Fallback: set all four vars — auth via client_credentials grant (legacy).
AZURE_PROMETHEUS_RESOURCE_ID = os.getenv("AZURE_PROMETHEUS_RESOURCE_ID", "")
AZURE_PROMETHEUS_TENANT_ID = os.getenv("AZURE_PROMETHEUS_TENANT_ID", "")
AZURE_PROMETHEUS_CLIENT_ID = os.getenv("AZURE_PROMETHEUS_CLIENT_ID", "")
AZURE_PROMETHEUS_CLIENT_SECRET = os.getenv("AZURE_PROMETHEUS_CLIENT_SECRET", "")

# Lazy-initialized credential for Azure Managed Prometheus MI path (reused across requests).
_azure_credential = None
_azure_credential_lock = asyncio.Lock()

# Token cache for client-secret fallback path.
_azure_token_cache: dict = {"token": "", "expires_at": 0.0}
_azure_token_cache_lock = asyncio.Lock()

router = APIRouter(
    prefix="/metrics-dashboard",
    tags=["Metrics Dashboard"],
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PromQLQuery(BaseModel):
    query: str
    time: Optional[str] = None


class PromQLRangeQuery(BaseModel):
    query: str
    start: str
    end: str
    step: str = "60s"


# ---------------------------------------------------------------------------
# KPI preset definitions
# ---------------------------------------------------------------------------

KPI_PRESETS = [
    {
        "id": "platform_uptime",
        "name": "Platform Uptime %",
        "section": "Platform Health",
        "query": "avg_over_time(up[24h]) * 100",
        "unit": "%",
        "thresholds": {"green": 99, "yellow": 95},
    },
    {
        "id": "api_latency_p95",
        "name": "API Latency P95",
        "section": "Platform Health",
        "query": "histogram_quantile(0.95, sum(rate(http_server_request_duration_ms_milliseconds_bucket[5m])) by (le))",
        "unit": "ms",
        "thresholds": {"green": 500, "yellow": 1000},
    },
    {
        "id": "api_latency_p99",
        "name": "API Latency P99",
        "section": "Platform Health",
        "query": "histogram_quantile(0.99, sum(rate(http_server_request_duration_ms_milliseconds_bucket[5m])) by (le))",
        "unit": "ms",
        "thresholds": {"green": 1000, "yellow": 2000},
    },
    {
        "id": "error_rate",
        "name": "Error Rate %",
        "section": "Platform Health",
        "query": "100 * sum(rate(agentcore_api_errors_total[5m])) / clamp_min(sum(rate(http_server_requests_total[5m])), 0.001)",
        "unit": "%",
        "thresholds": {"green": 5, "yellow": 10},
    },
    {
        "id": "avg_session_duration",
        "name": "Avg Session Duration",
        "section": "Experience",
        "query": "avg(agentcore_session_duration_ms_milliseconds_sum / clamp_min(agentcore_session_duration_ms_milliseconds_count, 1))",
        "unit": "ms",
        "thresholds": {"green": 0, "yellow": 0},
    },
    {
        "id": "avg_response_time",
        "name": "Avg Response Time",
        "section": "Experience",
        "query": "sum(rate(http_server_request_duration_ms_milliseconds_sum[5m])) / clamp_min(sum(rate(http_server_request_duration_ms_milliseconds_count[5m])), 0.001)",
        "unit": "ms",
        "thresholds": {"green": 200, "yellow": 500},
    },
    {
        "id": "avg_agent_latency",
        "name": "Avg Agent Latency",
        "section": "Developer Performance",
        "query": "avg(rate(agentcore_agent_run_duration_ms_milliseconds_sum[5m]) / clamp_min(rate(agentcore_agent_run_duration_ms_milliseconds_count[5m]), 0.001))",
        "unit": "ms",
        "thresholds": {"green": 2000, "yellow": 5000},
    },
    {
        "id": "agent_latency_p95",
        "name": "Agent Latency P95",
        "section": "Developer Performance",
        "query": "histogram_quantile(0.95, sum(rate(agentcore_agent_run_duration_ms_milliseconds_bucket[5m])) by (le))",
        "unit": "ms",
        "thresholds": {"green": 5000, "yellow": 10000},
    },
    {
        "id": "agent_latency_p99",
        "name": "Agent Latency P99",
        "section": "Developer Performance",
        "query": "histogram_quantile(0.99, sum(rate(agentcore_agent_run_duration_ms_milliseconds_bucket[5m])) by (le))",
        "unit": "ms",
        "thresholds": {"green": 10000, "yellow": 20000},
    },
    {
        "id": "running_pods",
        "name": "Running Pods",
        "section": "Infrastructure",
        "query": 'sum(kube_pod_status_phase{phase="Running"})',
        "unit": "pods",
        "thresholds": {"green": 0, "yellow": 0},
    },
    {
        "id": "pending_pods",
        "name": "Pending Pods",
        "section": "Infrastructure",
        "query": 'sum(kube_pod_status_phase{phase="Pending"}) or vector(0)',
        "unit": "pods",
        "thresholds": {"green": 5, "yellow": 10},
    },
    {
        "id": "pod_restarts_24h",
        "name": "Pod Restarts (24h)",
        "section": "Infrastructure",
        "query": "sum(increase(kube_pod_container_status_restarts_total[24h]))",
        "unit": "restarts",
        "thresholds": {"green": 10, "yellow": 25},
    },
    {
        "id": "hpa_replicas",
        "name": "HPA Current Replicas",
        "section": "Infrastructure",
        "query": "sum(kube_horizontalpodautoscaler_status_current_replicas)",
        "unit": "replicas",
        "thresholds": {"green": 0, "yellow": 0},
    },
    {
        "id": "cpu_saturation",
        "name": "CPU Saturation %",
        "section": "Infrastructure",
        "query": (
            "100 * avg(rate(container_cpu_usage_seconds_total"
            '{container!="POD", container!=""}[5m]))'
        ),
        "unit": "%",
        "thresholds": {"green": 70, "yellow": 85},
    },
    {
        "id": "memory_saturation",
        "name": "Memory Saturation %",
        "section": "Infrastructure",
        "query": (
            "100 * sum(container_memory_working_set_bytes"
            '{container!="POD", container!=""})'
            ' / sum(kube_node_status_capacity{resource="memory"})'
        ),
        "unit": "%",
        "thresholds": {"green": 70, "yellow": 85},
    },
]

CHART_PRESETS = [
    {
        "id": "api_latency_comparison",
        "name": "API Latency P95 vs P99",
        "type": "line",
        "queries": [
            {"label": "P95", "query": "histogram_quantile(0.95, sum(rate(http_server_request_duration_ms_milliseconds_bucket[5m])) by (le))"},
            {"label": "P99", "query": "histogram_quantile(0.99, sum(rate(http_server_request_duration_ms_milliseconds_bucket[5m])) by (le))"},
        ],
        "unit": "ms",
    },
    {
        "id": "error_rate_trend",
        "name": "Error Rate Trend",
        "type": "area",
        "queries": [
            {"label": "Error Rate", "query": "100 * sum(rate(agentcore_api_errors_total[5m])) / clamp_min(sum(rate(http_server_requests_total[5m])), 0.001)"},
        ],
        "unit": "%",
    },
    {
        "id": "response_time_trend",
        "name": "Response Time Trend",
        "type": "line",
        "queries": [
            {"label": "Avg Response Time", "query": "sum(rate(http_server_request_duration_ms_milliseconds_sum[5m])) / clamp_min(sum(rate(http_server_request_duration_ms_milliseconds_count[5m])), 0.001)"},
        ],
        "unit": "ms",
    },
    {
        "id": "agent_latency_comparison",
        "name": "Agent Latency P95 vs P99",
        "type": "line",
        "queries": [
            {"label": "P95", "query": "histogram_quantile(0.95, sum(rate(agentcore_agent_run_duration_ms_milliseconds_bucket[5m])) by (le))"},
            {"label": "P99", "query": "histogram_quantile(0.99, sum(rate(agentcore_agent_run_duration_ms_milliseconds_bucket[5m])) by (le))"},
        ],
        "unit": "ms",
    },
    {
        "id": "platform_uptime_trend",
        "name": "Platform Uptime",
        "type": "area",
        "queries": [
            {"label": "Uptime", "query": "avg_over_time(up[24h]) * 100"},
        ],
        "unit": "%",
    },
    {
        "id": "pod_scaling_activity",
        "name": "Pod Scaling Activity",
        "type": "line",
        "queries": [
            {"label": "Running Pods", "query": 'sum(kube_pod_status_phase{phase="Running"})'},
            {"label": "Desired Replicas (HPA)", "query": "sum(kube_horizontalpodautoscaler_status_desired_replicas)"},
        ],
        "unit": "pods",
    },
    {
        "id": "pod_restarts_trend",
        "name": "Pod Restarts Over Time",
        "type": "bar",
        "queries": [
            {"label": "Restarts", "query": "sum(increase(kube_pod_container_status_restarts_total[1h]))"},
        ],
        "unit": "restarts",
    },
    {
        "id": "cpu_memory_saturation",
        "name": "CPU & Memory Saturation",
        "type": "line",
        "queries": [
            {
                "label": "CPU %",
                "query": (
                    "100 * avg(rate(container_cpu_usage_seconds_total"
                    '{container!="POD", container!=""}[5m]))'
                ),
            },
            {
                "label": "Memory %",
                "query": (
                    "100 * sum(container_memory_working_set_bytes"
                    '{container!="POD", container!=""})'
                    ' / sum(kube_node_status_capacity{resource="memory"})'
                ),
            },
        ],
        "unit": "%",
    },
]


_KPI_PRESET_MAP: dict[str, dict] = {p["id"]: p for p in KPI_PRESETS}
_CHART_PRESET_MAP: dict[str, dict] = {p["id"]: p for p in CHART_PRESETS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_client_secret_config() -> bool:
    """Return True if legacy client-secret credentials are fully configured."""
    return bool(
        AZURE_PROMETHEUS_TENANT_ID
        and AZURE_PROMETHEUS_CLIENT_ID
        and AZURE_PROMETHEUS_CLIENT_SECRET
    )


def _is_azure_prometheus() -> bool:
    """Return True if Azure Managed Prometheus is configured (MI or client-secret)."""
    return bool(AZURE_PROMETHEUS_RESOURCE_ID) or _has_client_secret_config()


async def _get_azure_token_via_mi() -> str:
    """Get token via DefaultAzureCredential (Managed Identity on AKS, Azure CLI locally)."""
    global _azure_credential
    async with _azure_credential_lock:
        if _azure_credential is None:
            from azure.identity import DefaultAzureCredential

            _azure_credential = DefaultAzureCredential(
                exclude_environment_credential=True,
                exclude_interactive_browser_credential=True,
            )

    token = await asyncio.to_thread(
        _azure_credential.get_token,
        "https://prometheus.monitor.azure.com/.default",
    )
    return token.token


async def _get_azure_token_via_client_secret() -> str:
    """Get token via OAuth2 client_credentials grant (legacy fallback)."""
    async with _azure_token_cache_lock:
        now = time.time()
        if _azure_token_cache["token"] and _azure_token_cache["expires_at"] > now + 60:
            return _azure_token_cache["token"]

        token_url = (
            f"https://login.microsoftonline.com/{AZURE_PROMETHEUS_TENANT_ID}/oauth2/v2.0/token"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": AZURE_PROMETHEUS_CLIENT_ID,
                    "client_secret": AZURE_PROMETHEUS_CLIENT_SECRET,
                    "scope": "https://prometheus.monitor.azure.com/.default",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        _azure_token_cache["token"] = data["access_token"]
        _azure_token_cache["expires_at"] = now + data.get("expires_in", 3600)
        logger.debug("Azure Prometheus token refreshed (client-secret), expires in %ss", data.get("expires_in"))
        return _azure_token_cache["token"]


async def _get_azure_token() -> str:
    """Get an Azure AD Bearer token for Prometheus.

    Strategy: try Managed Identity first (preferred, more secure).
    If MI fails and client-secret credentials are configured, fall back to
    the legacy client_credentials grant.
    """
    if _has_client_secret_config():
        # Client-secret is configured — try MI first, fall back to client-secret.
        try:
            return await _get_azure_token_via_mi()
        except Exception as mi_err:
            logger.info("MI token failed (%s), falling back to client-secret", mi_err)
            return await _get_azure_token_via_client_secret()

    # No client-secret configured — MI is the only option.
    return await _get_azure_token_via_mi()


async def _prometheus_headers() -> dict:
    """Build headers for Prometheus requests, including Azure auth if configured."""
    headers: dict = {"Accept": "application/json"}
    if _is_azure_prometheus():
        token = await _get_azure_token()
        headers["Authorization"] = f"Bearer {token}"
        if AZURE_PROMETHEUS_RESOURCE_ID:
            headers["x-ms-azure-resource-id"] = AZURE_PROMETHEUS_RESOURCE_ID
    return headers


def _grafana_headers() -> dict:
    headers = {"Accept": "application/json"}
    if GRAFANA_API_KEY:
        headers["Authorization"] = f"Bearer {GRAFANA_API_KEY}"
    return headers


def _require_admin(user: User, *, allowed: set[str] | None = None) -> str:
    if allowed is None:
        allowed = {"root", "super_admin"}
    role = normalize_role(getattr(user, "role", None) or "developer")
    if role not in allowed:
        raise HTTPException(status_code=403, detail=f"This endpoint requires one of {sorted(allowed)} roles")
    return role


# Type aliases (mirrors api/utils.py)
CurrentActiveUser = Annotated[User, Depends(get_current_active_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Analytics scoping helpers (copied from agent.py to avoid coupling)
# ---------------------------------------------------------------------------

async def _get_scope_memberships(session: AsyncSession, user_id: UUID) -> tuple[set[UUID], set[UUID]]:
    """Return (org_ids, dept_ids) the user belongs to."""
    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    dept_ids = {r if isinstance(r, UUID) else r[0] for r in dept_rows}
    return org_ids, dept_ids


def _scope_label(role: str) -> str:
    """Human-readable scope label for the response."""
    if role == "root":
        return "platform"
    if role == "super_admin":
        return "organization"
    if role == "department_admin":
        return "department"
    return "user"


def _period_to_cutoff(period: str) -> datetime:
    """Convert a period string like '7d' to a UTC cutoff datetime."""
    days_map = {"7d": 7, "30d": 30, "90d": 90}
    days = days_map.get(period, 30)
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


async def _scoped_agent_ids(
    session: AsyncSession, user: User,
) -> tuple[str, list[UUID] | None]:
    """Return (scope_label, agent_id_list_or_None).

    None means 'all agents' (root).  Otherwise the list restricts queries.
    """
    role = normalize_role(getattr(user, "role", None) or "developer")

    if role == "root":
        return "platform", None

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, user.id)
        if org_ids:
            rows = (
                await session.exec(
                    select(Agent.id).where(
                        or_(
                            Agent.org_id.in_(list(org_ids)),
                            Agent.user_id == user.id,
                        ),
                        Agent.deleted_at.is_(None),
                    )
                )
            ).all()
            return "organization", [r if isinstance(r, UUID) else r[0] for r in rows]
        # No org memberships — fall through to own data only
        rows = (await session.exec(select(Agent.id).where(Agent.user_id == user.id, Agent.deleted_at.is_(None)))).all()
        return "organization", [r if isinstance(r, UUID) else r[0] for r in rows]

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, user.id)
        if dept_ids:
            rows = (
                await session.exec(
                    select(Agent.id).where(
                        or_(
                            Agent.dept_id.in_(list(dept_ids)),
                            Agent.user_id == user.id,
                        ),
                        Agent.deleted_at.is_(None),
                    )
                )
            ).all()
            return "department", [r if isinstance(r, UUID) else r[0] for r in rows]
        rows = (await session.exec(select(Agent.id).where(Agent.user_id == user.id, Agent.deleted_at.is_(None)))).all()
        return "department", [r if isinstance(r, UUID) else r[0] for r in rows]

    # developer / business_user — own agents only
    rows = (await session.exec(select(Agent.id).where(Agent.user_id == user.id, Agent.deleted_at.is_(None)))).all()
    return "user", [r if isinstance(r, UUID) else r[0] for r in rows]


# ---------------------------------------------------------------------------
# Endpoints — Prometheus
# ---------------------------------------------------------------------------

@router.get("/status")
async def metrics_status(
    current_user: CurrentActiveUser,
):
    """Check Prometheus + Grafana connectivity."""
    result = {"prometheus": {"status": "unknown"}, "grafana": {"status": "unknown"}}

    prom_headers = await _prometheus_headers()

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{PROMETHEUS_URL}/-/healthy", headers=prom_headers)
            result["prometheus"] = {
                "status": "connected" if resp.status_code == 200 else "error",
            }
        except Exception as e:
            result["prometheus"] = {"status": "unreachable", "error": str(e)}

        try:
            resp = await client.get(f"{GRAFANA_URL}/api/health", headers=_grafana_headers())
            result["grafana"] = {
                "status": "connected" if resp.status_code == 200 else "error",
            }
        except Exception as e:
            result["grafana"] = {"status": "unreachable", "error": str(e)}

    return result


@router.post("/query")
async def prometheus_query(
    body: PromQLQuery,
    current_user: User = Depends(get_current_active_user),
):
    """Run an instant PromQL query. Admin only."""
    _require_admin(current_user)
    params = {"query": body.query}
    if body.time:
        params["time"] = body.time

    prom_headers = await _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query", params=params, headers=prom_headers,
            )
            return resp.json()
        except httpx.ConnectError:
            return {"status": "error", "error": "Prometheus is unreachable"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


@router.post("/query_range")
async def prometheus_query_range(
    body: PromQLRangeQuery,
    current_user: User = Depends(get_current_active_user),
):
    """Run a range PromQL query. Admin only."""
    _require_admin(current_user)
    params = {
        "query": body.query,
        "start": body.start,
        "end": body.end,
        "step": body.step,
    }

    prom_headers = await _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query_range", params=params, headers=prom_headers,
            )
            return resp.json()
        except httpx.ConnectError:
            return {"status": "error", "error": "Prometheus is unreachable"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


@router.get("/presets")
async def get_presets(
    current_user: User = Depends(get_current_active_user),
):
    """Return the KPI definitions with their PromQL + chart presets + available analytics."""
    role = normalize_role(getattr(current_user, "role", None) or "developer")

    # All authenticated users get these
    analytics_endpoints = [
        "/analytics/summary",
        "/analytics/agents",
        "/analytics/usage-over-time",
    ]
    # Admin-only endpoints
    if role in ("root", "super_admin", "department_admin"):
        analytics_endpoints.append("/analytics/users")
    if role in ("root", "super_admin"):
        analytics_endpoints.append("/analytics/departments")

    return {"kpis": KPI_PRESETS, "charts": CHART_PRESETS, "analytics": analytics_endpoints}


@router.get("/query-preset/{preset_id}")
async def query_preset(
    preset_id: str,
    current_user: CurrentActiveUser,
    time: Optional[str] = Query(None, description="Evaluation timestamp (RFC3339 or unix)"),
):
    """Run a predefined KPI query by preset ID. Any authenticated user."""
    preset = _KPI_PRESET_MAP.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")

    params: dict[str, str] = {"query": preset["query"]}
    if time:
        params["time"] = time

    prom_headers = await _prometheus_headers()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query", params=params, headers=prom_headers,
            )
            data = resp.json()
        except httpx.ConnectError:
            data = {"status": "error", "error": "Prometheus is unreachable"}
        except Exception as e:
            data = {"status": "error", "error": str(e)}

    return {
        "preset": {
            "id": preset["id"],
            "name": preset["name"],
            "section": preset["section"],
            "unit": preset["unit"],
            "thresholds": preset["thresholds"],
        },
        "prometheus": data,
    }


@router.get("/query-preset-range/{preset_id}")
async def query_preset_range(
    preset_id: str,
    current_user: CurrentActiveUser,
    start: Optional[str] = Query(None, description="Range start (RFC3339 or unix)"),
    end: Optional[str] = Query(None, description="Range end (RFC3339 or unix)"),
    step: str = Query("60s", description="Query resolution step"),
):
    """Run a predefined KPI or chart range query by preset ID. Any authenticated user."""
    kpi = _KPI_PRESET_MAP.get(preset_id)
    chart = _CHART_PRESET_MAP.get(preset_id)

    if not kpi and not chart:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")

    # Default range: 1 hour ago to now
    now_ts = str(int(time.time()))
    default_start = str(int(time.time()) - 3600)
    range_start = start or default_start
    range_end = end or now_ts

    prom_headers = await _prometheus_headers()

    if kpi:
        # Single KPI range query
        params = {"query": kpi["query"], "start": range_start, "end": range_end, "step": step}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query_range", params=params, headers=prom_headers,
                )
                data = resp.json()
            except httpx.ConnectError:
                data = {"status": "error", "error": "Prometheus is unreachable"}
            except Exception as e:
                data = {"status": "error", "error": str(e)}

        return {
            "preset": {
                "id": kpi["id"],
                "name": kpi["name"],
                "section": kpi["section"],
                "unit": kpi["unit"],
                "thresholds": kpi["thresholds"],
            },
            "series": [{"label": kpi["name"], "prometheus": data}],
        }

    # Chart preset — multiple queries
    series = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for q_def in chart["queries"]:
            params = {"query": q_def["query"], "start": range_start, "end": range_end, "step": step}
            try:
                resp = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query_range", params=params, headers=prom_headers,
                )
                data = resp.json()
            except httpx.ConnectError:
                data = {"status": "error", "error": "Prometheus is unreachable"}
            except Exception as e:
                data = {"status": "error", "error": str(e)}
            series.append({"label": q_def["label"], "prometheus": data})

    return {
        "preset": {
            "id": chart["id"],
            "name": chart["name"],
            "type": chart["type"],
            "unit": chart["unit"],
        },
        "series": series,
    }


# ---------------------------------------------------------------------------
# Endpoints — Grafana
# ---------------------------------------------------------------------------

@router.get("/grafana/dashboards")
async def grafana_dashboards(
    current_user: User = Depends(get_current_active_user),
):
    """List all Grafana dashboards. Admin only."""
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{GRAFANA_URL}/api/search",
                headers=_grafana_headers(),
                params={"type": "dash-db"},
            )
            return resp.json()
        except httpx.ConnectError:
            return {"status": "error", "error": "Grafana is unreachable"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


@router.get("/grafana/dashboard/{uid}")
async def grafana_dashboard_detail(
    uid: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get full dashboard JSON by UID. Admin only."""
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{GRAFANA_URL}/api/dashboards/uid/{uid}",
                headers=_grafana_headers(),
            )
            return resp.json()
        except httpx.ConnectError:
            return {"status": "error", "error": "Grafana is unreachable"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


@router.get("/grafana/embed-url/{uid}")
async def grafana_embed_url(
    uid: str,
    current_user: User = Depends(get_current_active_user),
):
    """Return an embeddable iframe URL for a Grafana dashboard. Admin only."""
    _require_admin(current_user)
    return {
        "embed_url": f"{GRAFANA_URL}/d/{uid}?kiosk&theme=light",
        "url": f"{GRAFANA_URL}/d/{uid}",
    }


# ---------------------------------------------------------------------------
# Endpoints — Scoped Analytics (DB-queried, org/dept/user aware)
# ---------------------------------------------------------------------------

@router.get("/analytics/summary")
async def analytics_summary(
    session: DbSession,
    current_user: CurrentActiveUser,
    period: Literal["7d", "30d", "90d"] = "30d",
):
    """Scoped usage summary — counts of agents, projects, builds, conversations."""
    try:
        role = normalize_role(getattr(current_user, "role", None) or "developer")
        scope, agent_ids = await _scoped_agent_ids(session, current_user)
        cutoff = _period_to_cutoff(period)

        # -- Agent count (not time-filtered; agents are long-lived) --
        agent_q = select(func.count()).select_from(Agent).where(Agent.deleted_at.is_(None))
        active_agent_q = select(func.count()).select_from(Agent).where(
            Agent.deleted_at.is_(None), Agent.updated_at >= cutoff,
        )
        if agent_ids is not None:
            agent_q = agent_q.where(Agent.id.in_(agent_ids))
            active_agent_q = active_agent_q.where(Agent.id.in_(agent_ids))

        total_agents = (await session.exec(agent_q)).one()
        active_agents = (await session.exec(active_agent_q)).one()

        # -- Project count --
        project_q = select(func.count()).select_from(Project)
        if role == "root":
            pass  # all projects
        elif role == "super_admin":
            org_ids, _ = await _get_scope_memberships(session, current_user.id)
            if org_ids:
                project_q = project_q.where(Project.org_id.in_(list(org_ids)))
            else:
                project_q = project_q.where(Project.owner_user_id == current_user.id)
        elif role == "department_admin":
            _, dept_ids = await _get_scope_memberships(session, current_user.id)
            if dept_ids:
                project_q = project_q.where(Project.dept_id.in_(list(dept_ids)))
            else:
                project_q = project_q.where(Project.owner_user_id == current_user.id)
        else:
            project_q = project_q.where(Project.owner_user_id == current_user.id)
        total_projects = (await session.exec(project_q)).one()

        # -- Build count (time-filtered) --
        build_q = select(func.count()).select_from(VertexBuildTable).where(
            VertexBuildTable.timestamp >= cutoff,
        )
        if agent_ids is not None:
            build_q = build_q.where(VertexBuildTable.agent_id.in_(agent_ids))
        total_builds = (await session.exec(build_q)).one()

        # -- Conversation count (time-filtered) --
        conv_q = select(func.count()).select_from(ConversationTable).where(
            ConversationTable.timestamp >= cutoff,
        )
        if agent_ids is not None:
            conv_q = conv_q.where(ConversationTable.agent_id.in_(agent_ids))
        total_conversations = (await session.exec(conv_q)).one()

        # -- User count (within scope) --
        if role == "root":
            user_q = select(func.count()).select_from(User).where(User.is_active.is_(True))
        elif role == "super_admin":
            org_ids, _ = await _get_scope_memberships(session, current_user.id)
            if org_ids:
                user_sub = select(UserOrganizationMembership.user_id).where(
                    UserOrganizationMembership.org_id.in_(list(org_ids)),
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                ).distinct()
                user_q = select(func.count()).select_from(User).where(
                    User.id.in_(user_sub), User.is_active.is_(True),
                )
            else:
                user_q = select(func.literal(1))
        elif role == "department_admin":
            _, dept_ids = await _get_scope_memberships(session, current_user.id)
            if dept_ids:
                user_sub = select(UserDepartmentMembership.user_id).where(
                    UserDepartmentMembership.department_id.in_(list(dept_ids)),
                    UserDepartmentMembership.status == "active",
                ).distinct()
                user_q = select(func.count()).select_from(User).where(
                    User.id.in_(user_sub), User.is_active.is_(True),
                )
            else:
                user_q = select(func.literal(1))
        else:
            user_q = select(func.literal(1))
        total_users = (await session.exec(user_q)).one()

        return {
            "scope": scope,
            "period": period,
            "summary": {
                "total_agents": total_agents,
                "active_agents": active_agents,
                "total_projects": total_projects,
                "total_builds": total_builds,
                "total_conversations": total_conversations,
                "total_users": total_users,
            },
        }
    except Exception as e:
        logger.exception("analytics/summary failed")
        raise HTTPException(status_code=500, detail=f"Analytics query failed: {e}")


@router.get("/analytics/agents")
async def analytics_agents(
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Per-agent stats scoped to the caller's visibility."""
    try:
        scope, agent_ids = await _scoped_agent_ids(session, current_user)

        # Build subqueries for counts
        build_count_sub = (
            select(
                VertexBuildTable.agent_id,
                func.count().label("build_count"),
                func.max(VertexBuildTable.timestamp).label("last_build_at"),
            )
            .group_by(VertexBuildTable.agent_id)
            .subquery()
        )
        conv_count_sub = (
            select(
                ConversationTable.agent_id,
                func.count().label("conversation_count"),
            )
            .group_by(ConversationTable.agent_id)
            .subquery()
        )

        q = (
            select(
                Agent.id,
                Agent.name,
                Agent.org_id,
                Agent.dept_id,
                Agent.user_id,
                User.username.label("owner_username"),
                build_count_sub.c.build_count,
                build_count_sub.c.last_build_at,
                conv_count_sub.c.conversation_count,
            )
            .outerjoin(User, Agent.user_id == User.id)
            .outerjoin(build_count_sub, Agent.id == build_count_sub.c.agent_id)
            .outerjoin(conv_count_sub, Agent.id == conv_count_sub.c.agent_id)
            .where(Agent.deleted_at.is_(None))
        )
        if agent_ids is not None:
            q = q.where(Agent.id.in_(agent_ids))

        rows = (await session.exec(q)).all()

        agents = []
        for row in rows:
            agents.append({
                "agent_id": str(row.id),
                "agent_name": row.name,
                "owner_username": row.owner_username,
                "org_id": str(row.org_id) if row.org_id else None,
                "dept_id": str(row.dept_id) if row.dept_id else None,
                "build_count": row.build_count or 0,
                "conversation_count": row.conversation_count or 0,
                "last_build_at": row.last_build_at.isoformat() if row.last_build_at else None,
            })

        return {"scope": scope, "agents": agents}
    except Exception as e:
        logger.exception("analytics/agents failed")
        raise HTTPException(status_code=500, detail=f"Analytics query failed: {e}")


@router.get("/analytics/usage-over-time")
async def analytics_usage_over_time(
    session: DbSession,
    current_user: CurrentActiveUser,
    period: Literal["7d", "30d", "90d"] = "30d",
    granularity: Literal["day", "week"] = "day",
):
    """Time-bucketed conversation and build counts."""
    try:
        scope, agent_ids = await _scoped_agent_ids(session, current_user)
        cutoff = _period_to_cutoff(period)

        # Conversations over time
        conv_bucket = func.date_trunc(granularity, ConversationTable.timestamp).label("bucket")
        conv_q = (
            select(conv_bucket, func.count().label("count"))
            .where(ConversationTable.timestamp >= cutoff)
            .group_by(conv_bucket)
            .order_by(conv_bucket)
        )
        if agent_ids is not None:
            conv_q = conv_q.where(ConversationTable.agent_id.in_(agent_ids))
        conv_rows = (await session.exec(conv_q)).all()

        # Builds over time
        build_bucket = func.date_trunc(granularity, VertexBuildTable.timestamp).label("bucket")
        build_q = (
            select(build_bucket, func.count().label("count"))
            .where(VertexBuildTable.timestamp >= cutoff)
            .group_by(build_bucket)
            .order_by(build_bucket)
        )
        if agent_ids is not None:
            build_q = build_q.where(VertexBuildTable.agent_id.in_(agent_ids))
        build_rows = (await session.exec(build_q)).all()

        def _series(rows):
            return [
                {"date": row.bucket.strftime("%Y-%m-%d") if row.bucket else None, "count": row.count}
                for row in rows
            ]

        return {
            "scope": scope,
            "period": period,
            "granularity": granularity,
            "series": {
                "conversations": _series(conv_rows),
                "builds": _series(build_rows),
            },
        }
    except Exception as e:
        logger.exception("analytics/usage-over-time failed")
        raise HTTPException(status_code=500, detail=f"Analytics query failed: {e}")


@router.get("/analytics/users")
async def analytics_users(
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Per-user usage stats. Only super_admin, department_admin, and root can access."""
    try:
        role = normalize_role(getattr(current_user, "role", None) or "developer")
        if role not in ("root", "super_admin", "department_admin"):
            raise HTTPException(status_code=403, detail="Insufficient role for user analytics")

        scope = _scope_label(role)

        # Determine which user IDs are in scope
        if role == "root":
            user_filter = User.is_active.is_(True)
        elif role == "super_admin":
            org_ids, _ = await _get_scope_memberships(session, current_user.id)
            if org_ids:
                user_sub = select(UserOrganizationMembership.user_id).where(
                    UserOrganizationMembership.org_id.in_(list(org_ids)),
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                ).distinct()
                user_filter = User.id.in_(user_sub)
            else:
                user_filter = User.id == current_user.id
        else:  # department_admin
            _, dept_ids = await _get_scope_memberships(session, current_user.id)
            if dept_ids:
                user_sub = select(UserDepartmentMembership.user_id).where(
                    UserDepartmentMembership.department_id.in_(list(dept_ids)),
                    UserDepartmentMembership.status == "active",
                ).distinct()
                user_filter = User.id.in_(user_sub)
            else:
                user_filter = User.id == current_user.id

        # Subquery: agent count per user
        agent_count_sub = (
            select(
                Agent.user_id,
                func.count().label("agent_count"),
            )
            .where(Agent.deleted_at.is_(None))
            .group_by(Agent.user_id)
            .subquery()
        )

        # Subquery: build count per user (via Agent)
        build_count_sub = (
            select(
                Agent.user_id,
                func.count(VertexBuildTable.build_id).label("build_count"),
            )
            .join(VertexBuildTable, Agent.id == VertexBuildTable.agent_id)
            .where(Agent.deleted_at.is_(None))
            .group_by(Agent.user_id)
            .subquery()
        )

        # Subquery: conversation count per user (via Agent)
        conv_count_sub = (
            select(
                Agent.user_id,
                func.count(ConversationTable.id).label("conversation_count"),
            )
            .join(ConversationTable, Agent.id == ConversationTable.agent_id)
            .where(Agent.deleted_at.is_(None))
            .group_by(Agent.user_id)
            .subquery()
        )

        q = (
            select(
                User.id,
                User.username,
                User.role,
                agent_count_sub.c.agent_count,
                build_count_sub.c.build_count,
                conv_count_sub.c.conversation_count,
            )
            .outerjoin(agent_count_sub, User.id == agent_count_sub.c.user_id)
            .outerjoin(build_count_sub, User.id == build_count_sub.c.user_id)
            .outerjoin(conv_count_sub, User.id == conv_count_sub.c.user_id)
            .where(user_filter)
        )

        rows = (await session.exec(q)).all()

        users = []
        for row in rows:
            users.append({
                "user_id": str(row.id),
                "username": row.username,
                "role": row.role,
                "agent_count": row.agent_count or 0,
                "build_count": row.build_count or 0,
                "conversation_count": row.conversation_count or 0,
            })

        return {"scope": scope, "users": users}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("analytics/users failed")
        raise HTTPException(status_code=500, detail=f"Analytics query failed: {e}")


@router.get("/analytics/departments")
async def analytics_departments(
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Per-department aggregates. Only super_admin and root can access."""
    try:
        role = normalize_role(getattr(current_user, "role", None) or "developer")
        if role not in ("root", "super_admin"):
            raise HTTPException(status_code=403, detail="Insufficient role for department analytics")

        scope = _scope_label(role)

        # Determine which departments are in scope
        dept_q = select(Department.id, Department.name, Department.org_id)
        if role == "super_admin":
            org_ids, _ = await _get_scope_memberships(session, current_user.id)
            if org_ids:
                dept_q = dept_q.where(Department.org_id.in_(list(org_ids)))
            else:
                return {"scope": scope, "departments": []}

        dept_rows = (await session.exec(dept_q)).all()

        departments = []
        for dept in dept_rows:
            dept_id = dept.id

            # User count in department
            user_count_q = select(func.count()).select_from(UserDepartmentMembership).where(
                UserDepartmentMembership.department_id == dept_id,
                UserDepartmentMembership.status == "active",
            )
            user_count = (await session.exec(user_count_q)).one()

            # Agent count in department
            agent_count_q = select(func.count()).select_from(Agent).where(
                Agent.dept_id == dept_id, Agent.deleted_at.is_(None),
            )
            agent_count = (await session.exec(agent_count_q)).one()

            # Build count in department (via agents)
            build_count_q = (
                select(func.count())
                .select_from(VertexBuildTable)
                .where(VertexBuildTable.dept_id == dept_id)
            )
            build_count = (await session.exec(build_count_q)).one()

            departments.append({
                "dept_id": str(dept_id),
                "dept_name": dept.name,
                "user_count": user_count,
                "agent_count": agent_count,
                "build_count": build_count,
            })

        return {"scope": scope, "departments": departments}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("analytics/departments failed")
        raise HTTPException(status_code=500, detail=f"Analytics query failed: {e}")
