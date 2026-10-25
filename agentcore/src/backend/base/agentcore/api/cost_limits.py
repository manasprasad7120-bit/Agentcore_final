"""Cost Limits API — CRUD + status polling for cost threshold alerts."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from loguru import logger
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.cost_limit.model import CostLimit
from agentcore.services.database.models.cost_limit_notification.model import CostLimitNotification
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.schema.cost_limit import (
    CostLimitCreate,
    CostLimitResponse,
    CostLimitStatus,
    CostLimitUpdate,
)

router = APIRouter(prefix="/cost-limits", tags=["Cost Limits"])


# ---------------------------------------------------------------------------
# Ensure tables exist (runs once on first request)
# ---------------------------------------------------------------------------

_tables_ensured = False

_CREATE_COST_LIMIT_SQL = """
CREATE TABLE IF NOT EXISTS cost_limit (
    id UUID PRIMARY KEY,
    scope_type VARCHAR(20) NOT NULL,
    org_id UUID NOT NULL REFERENCES organization(id),
    dept_id UUID REFERENCES department(id),
    limit_amount_usd NUMERIC(12,4) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    period_type VARCHAR(20) NOT NULL DEFAULT 'monthly',
    period_start_day INTEGER NOT NULL DEFAULT 1,
    warning_threshold_pct INTEGER NOT NULL DEFAULT 80,
    action_on_breach VARCHAR(30) NOT NULL DEFAULT 'notify_only',
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMPTZ,
    last_breach_at TIMESTAMPTZ,
    last_warning_at TIMESTAMPTZ,
    current_period_cost_usd NUMERIC(12,4) DEFAULT 0,
    current_period_start TIMESTAMPTZ,
    created_by UUID NOT NULL REFERENCES "user"(id),
    updated_by UUID REFERENCES "user"(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_CREATE_COST_LIMIT_NOTIFICATION_SQL = """
CREATE TABLE IF NOT EXISTS cost_limit_notification (
    id UUID PRIMARY KEY,
    cost_limit_id UUID NOT NULL REFERENCES cost_limit(id) ON DELETE CASCADE,
    notification_type VARCHAR(20) NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    cost_at_notification NUMERIC(12,4) NOT NULL,
    limit_amount_usd NUMERIC(12,4) NOT NULL,
    percentage_used NUMERIC(5,2) NOT NULL,
    dismissed_by_user_ids UUID[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cost_limit_notification_period UNIQUE (cost_limit_id, notification_type, period_start)
);
"""

_CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS ix_cost_limit_org_id ON cost_limit(org_id);
CREATE INDEX IF NOT EXISTS ix_cost_limit_dept_id ON cost_limit(dept_id);
CREATE INDEX IF NOT EXISTS ix_cost_limit_notification_cost_limit_id ON cost_limit_notification(cost_limit_id);
"""


async def _ensure_tables(session: DbSession) -> None:
    global _tables_ensured
    if _tables_ensured:
        return
    try:
        from sqlmodel import text as sql_text
        await session.exec(sql_text(_CREATE_COST_LIMIT_SQL))
        await session.exec(sql_text(_CREATE_COST_LIMIT_NOTIFICATION_SQL))
        await session.exec(sql_text(_CREATE_INDEXES_SQL))
        await session.commit()
        _tables_ensured = True
        logger.info("cost_limit and cost_limit_notification tables ensured")
    except Exception:
        _tables_ensured = True  # Don't retry on every request
        logger.opt(exception=True).warning("Failed to ensure cost_limit tables (may already exist)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_role(user: CurrentActiveUser) -> str:
    return str(getattr(user, "role", "")).strip().lower()


def _is_admin_role(role: str) -> bool:
    return role in {"root", "super_admin", "department_admin"}


async def _user_org_ids(session: DbSession, user: CurrentActiveUser) -> set[UUID]:
    """Return org IDs where the user has an active membership."""
    rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user.id,
                UserOrganizationMembership.status == "active",
            )
        )
    ).all()
    return {r if isinstance(r, UUID) else r[0] for r in rows}


async def _user_admin_dept_ids(session: DbSession, user: CurrentActiveUser) -> set[UUID]:
    """Return department IDs where the user is the admin."""
    rows = (
        await session.exec(
            select(Department.id).where(Department.admin_user_id == user.id)
        )
    ).all()
    return {r if isinstance(r, UUID) else r[0] for r in rows}


async def _validate_scope_ownership(
    session: DbSession,
    user: CurrentActiveUser,
    scope_type: str,
    org_id: UUID,
    dept_id: UUID | None,
) -> None:
    """Ensure the user is allowed to manage a cost limit for the given scope."""
    role = _get_role(user)
    if role == "root":
        return

    if scope_type == "organization":
        if role != "super_admin":
            raise HTTPException(status_code=403, detail="Only super admins can set organization-level cost limits.")
        org_ids = await _user_org_ids(session, user)
        if org_id not in org_ids:
            raise HTTPException(status_code=403, detail="You are not a member of this organization.")

    elif scope_type == "department":
        if role == "super_admin":
            org_ids = await _user_org_ids(session, user)
            if org_id not in org_ids:
                raise HTTPException(status_code=403, detail="You are not a member of this organization.")
        elif role == "department_admin":
            dept_ids = await _user_admin_dept_ids(session, user)
            if dept_id not in dept_ids:
                raise HTTPException(status_code=403, detail="You are not the admin of this department.")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")


async def _enrich_response(session: DbSession, limit: CostLimit) -> CostLimitResponse:
    """Build a CostLimitResponse with org/dept names resolved."""
    org_name = None
    dept_name = None

    org = (await session.exec(select(Organization).where(Organization.id == limit.org_id))).first()
    if org:
        org_name = org.name

    if limit.dept_id:
        dept = (await session.exec(select(Department).where(Department.id == limit.dept_id))).first()
        if dept:
            dept_name = dept.name

    return CostLimitResponse(
        id=limit.id,
        scope_type=str(limit.scope_type),
        org_id=limit.org_id,
        org_name=org_name,
        dept_id=limit.dept_id,
        dept_name=dept_name,
        limit_amount_usd=float(limit.limit_amount_usd or 0),
        currency=limit.currency,
        period_type=str(limit.period_type),
        period_start_day=limit.period_start_day,
        warning_threshold_pct=limit.warning_threshold_pct,
        action_on_breach=str(limit.action_on_breach),
        is_enabled=limit.is_enabled,
        current_period_cost_usd=float(limit.current_period_cost_usd or 0),
        last_checked_at=limit.last_checked_at,
        last_breach_at=limit.last_breach_at,
        last_warning_at=limit.last_warning_at,
        created_at=limit.created_at,
        updated_at=limit.updated_at,
    )


# ---------------------------------------------------------------------------
# Period calculation
# ---------------------------------------------------------------------------


def _compute_current_period(period_type: str, period_start_day: int) -> tuple[datetime, datetime]:
    """Return (period_start, period_end) in UTC for the current billing period."""
    now = datetime.now(timezone.utc)

    if period_type in ("monthly", "custom"):
        day = min(period_start_day, 28)
        if now.day >= day:
            period_start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
        else:
            # Roll back to previous month
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_month_end = first_of_month - timedelta(days=1)
            period_start = prev_month_end.replace(day=day, hour=0, minute=0, second=0, microsecond=0)

        # Period end = next month on the same day
        if period_start.month == 12:
            period_end = period_start.replace(year=period_start.year + 1, month=1)
        else:
            period_end = period_start.replace(month=period_start.month + 1)

    elif period_type == "quarterly":
        day = min(period_start_day, 28)
        quarter_start_months = [1, 4, 7, 10]
        current_quarter = max(m for m in quarter_start_months if m <= now.month)
        period_start = now.replace(month=current_quarter, day=day, hour=0, minute=0, second=0, microsecond=0)
        if period_start > now:
            idx = quarter_start_months.index(current_quarter)
            prev_idx = (idx - 1) % 4
            prev_month = quarter_start_months[prev_idx]
            prev_year = now.year if prev_month < now.month else now.year - 1
            period_start = now.replace(year=prev_year, month=prev_month, day=day, hour=0, minute=0, second=0, microsecond=0)

        idx = quarter_start_months.index(period_start.month)
        next_idx = (idx + 1) % 4
        next_month = quarter_start_months[next_idx]
        next_year = period_start.year if next_month > period_start.month else period_start.year + 1
        period_end = period_start.replace(year=next_year, month=next_month)
    else:
        # Fallback to monthly
        return _compute_current_period("monthly", period_start_day)

    return period_start, period_end


# ---------------------------------------------------------------------------
# Cost aggregation via observability pipeline
# ---------------------------------------------------------------------------

_cost_cache: dict[str, tuple[float, float]] = {}
_COST_CACHE_TTL = 60.0


async def _fetch_cost_for_scope(
    session: DbSession,
    user: CurrentActiveUser,
    org_id: UUID,
    dept_id: UUID | None,
    period_start: datetime,
    period_end: datetime,
) -> float:
    """Fetch total cost USD for a scope within a period, using the observability pipeline."""
    scope_key = f"cost:{org_id}:{dept_id}:{period_start.isoformat()}"
    cached = _cost_cache.get(scope_key)
    if cached and (time.monotonic() - cached[1]) < _COST_CACHE_TTL:
        return cached[0]

    try:
        from agentcore.api.observability.scope import resolve_scope_context
        from agentcore.api.observability.trace_store import TraceStore
        from agentcore.api.observability.aggregations import aggregate_metrics

        trace_scope = "dept" if dept_id else "all"
        allowed_user_ids, clients, sk, _ = await resolve_scope_context(
            session=session,
            current_user=user,
            org_id=org_id,
            dept_id=dept_id,
            trace_scope=trace_scope,
        )

        if not clients:
            _cost_cache[scope_key] = (0.0, time.monotonic())
            return 0.0

        traces, _ = TraceStore.get_traces(
            clients=clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=sk,
            from_timestamp=period_start,
            to_timestamp=period_end,
            fetch_all=True,
        )

        metrics = aggregate_metrics(traces)
        total_cost = float(metrics.get("total_cost_usd", 0.0))

    except Exception:
        logger.opt(exception=True).warning("Failed to fetch cost for scope {scope_key}")
        total_cost = 0.0

    _cost_cache[scope_key] = (total_cost, time.monotonic())
    return total_cost


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("")
@router.get("/")
async def list_cost_limits(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> list[CostLimitResponse]:
    await _ensure_tables(session)
    role = _get_role(current_user)
    if not _is_admin_role(role):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    if role == "root":
        limits = (await session.exec(select(CostLimit).order_by(CostLimit.created_at.desc()))).all()
    elif role == "super_admin":
        org_ids = await _user_org_ids(session, current_user)
        if not org_ids:
            return []
        # Super admin sees all limits (org-level + dept-level) within their orgs
        limits = (
            await session.exec(
                select(CostLimit)
                .where(CostLimit.org_id.in_(list(org_ids)))
                .order_by(CostLimit.created_at.desc())
            )
        ).all()
    else:  # department_admin — only sees dept-level limits for their own depts
        dept_ids = await _user_admin_dept_ids(session, current_user)
        if not dept_ids:
            return []
        limits = (
            await session.exec(
                select(CostLimit)
                .where(CostLimit.dept_id.in_(list(dept_ids)))
                .order_by(CostLimit.created_at.desc())
            )
        ).all()

    return [await _enrich_response(session, lim) for lim in limits]


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_cost_limit(
    payload: CostLimitCreate,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> CostLimitResponse:
    await _ensure_tables(session)
    role = _get_role(current_user)
    if not _is_admin_role(role):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    await _validate_scope_ownership(session, current_user, payload.scope_type, payload.org_id, payload.dept_id)

    # Check for duplicate scope
    existing = (
        await session.exec(
            select(CostLimit).where(
                CostLimit.org_id == payload.org_id,
                CostLimit.dept_id == payload.dept_id if payload.dept_id else CostLimit.dept_id.is_(None),
            )
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A cost limit already exists for this scope.")

    now = datetime.now(timezone.utc)
    period_type_val = payload.period_type
    period_start, _ = _compute_current_period(period_type_val, payload.period_start_day)

    limit = CostLimit(
        scope_type=payload.scope_type,
        org_id=payload.org_id,
        dept_id=payload.dept_id,
        limit_amount_usd=payload.limit_amount_usd,
        warning_threshold_pct=payload.warning_threshold_pct,
        period_type=period_type_val,
        period_start_day=payload.period_start_day,
        action_on_breach=payload.action_on_breach,
        current_period_start=period_start,
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(limit)
    await session.commit()
    await session.refresh(limit)

    return await _enrich_response(session, limit)


@router.put("/{limit_id}")
async def update_cost_limit(
    limit_id: UUID,
    payload: CostLimitUpdate,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> CostLimitResponse:
    role = _get_role(current_user)
    if not _is_admin_role(role):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    limit = (await session.exec(select(CostLimit).where(CostLimit.id == limit_id))).first()
    if not limit:
        raise HTTPException(status_code=404, detail="Cost limit not found.")

    scope_type_str = str(limit.scope_type)
    await _validate_scope_ownership(session, current_user, scope_type_str, limit.org_id, limit.dept_id)

    if payload.limit_amount_usd is not None:
        limit.limit_amount_usd = payload.limit_amount_usd
    if payload.warning_threshold_pct is not None:
        limit.warning_threshold_pct = payload.warning_threshold_pct
    if payload.period_type is not None:
        limit.period_type = payload.period_type
    if payload.period_start_day is not None:
        limit.period_start_day = payload.period_start_day
    if payload.action_on_breach is not None:
        limit.action_on_breach = payload.action_on_breach
    if payload.is_enabled is not None:
        limit.is_enabled = payload.is_enabled

    limit.updated_by = current_user.id
    limit.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(limit)

    return await _enrich_response(session, limit)


@router.delete("/{limit_id}")
async def delete_cost_limit(
    limit_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> dict:
    role = _get_role(current_user)
    if not _is_admin_role(role):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    limit = (await session.exec(select(CostLimit).where(CostLimit.id == limit_id))).first()
    if not limit:
        raise HTTPException(status_code=404, detail="Cost limit not found.")

    scope_type_str = str(limit.scope_type)
    await _validate_scope_ownership(session, current_user, scope_type_str, limit.org_id, limit.dept_id)

    await session.delete(limit)
    await session.commit()

    return {"detail": "Cost limit deleted."}


# ---------------------------------------------------------------------------
# Status polling endpoint
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_cost_limit_status(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> list[CostLimitStatus]:
    await _ensure_tables(session)
    role = _get_role(current_user)
    if not _is_admin_role(role):
        return []

    # Determine which cost limits apply to this user
    if role == "root":
        limits = (
            await session.exec(select(CostLimit).where(CostLimit.is_enabled.is_(True)))
        ).all()
    elif role == "super_admin":
        org_ids = await _user_org_ids(session, current_user)
        if not org_ids:
            return []
        # Super admin sees all limits (org-level + dept-level) within their orgs
        limits = (
            await session.exec(
                select(CostLimit).where(
                    CostLimit.is_enabled.is_(True),
                    CostLimit.org_id.in_(list(org_ids)),
                )
            )
        ).all()
    else:  # department_admin — only sees dept-level limits for their own depts
        dept_ids = await _user_admin_dept_ids(session, current_user)
        if not dept_ids:
            return []
        limits = (
            await session.exec(
                select(CostLimit).where(
                    CostLimit.is_enabled.is_(True),
                    CostLimit.dept_id.in_(list(dept_ids)),
                )
            )
        ).all()

    statuses: list[CostLimitStatus] = []
    now = datetime.now(timezone.utc)

    for limit in limits:
        period_type_str = str(limit.period_type)
        period_start, period_end = _compute_current_period(period_type_str, limit.period_start_day)

        # Fetch aggregated cost
        current_cost = await _fetch_cost_for_scope(
            session, current_user, limit.org_id, limit.dept_id, period_start, period_end,
        )

        limit_usd = float(limit.limit_amount_usd or 0)
        pct_used = round((current_cost / limit_usd) * 100, 2) if limit_usd > 0 else 0.0
        is_warning = pct_used >= limit.warning_threshold_pct and pct_used < 100
        is_breached = pct_used >= 100

        # Update cached cost on the limit record
        limit.current_period_cost_usd = current_cost
        limit.current_period_start = period_start
        limit.last_checked_at = now

        # Resolve scope name
        scope_type_str_val = str(limit.scope_type)
        scope_name = ""
        if scope_type_str_val == "organization":
            org = (await session.exec(select(Organization.name).where(Organization.id == limit.org_id))).first()
            scope_name = str(org) if org else "Unknown Org"
        else:
            dept = (await session.exec(select(Department.name).where(Department.id == limit.dept_id))).first()
            scope_name = str(dept) if dept else "Unknown Dept"

        # Create/find notification if threshold crossed
        notification_id = None
        dismissed = False

        if is_breached or is_warning:
            notif_type = "breach" if is_breached else "warning"

            # Check if notification already exists for this period
            existing_notif = (
                await session.exec(
                    select(CostLimitNotification).where(
                        CostLimitNotification.cost_limit_id == limit.id,
                        CostLimitNotification.notification_type == notif_type,
                        CostLimitNotification.period_start == period_start,
                    )
                )
            ).first()

            if existing_notif:
                notification_id = existing_notif.id
                dismissed = (
                    current_user.id in (existing_notif.dismissed_by_user_ids or [])
                )
            else:
                # Create new notification
                new_notif = CostLimitNotification(
                    cost_limit_id=limit.id,
                    notification_type=notif_type,
                    period_start=period_start,
                    period_end=period_end,
                    cost_at_notification=current_cost,
                    limit_amount_usd=limit_usd,
                    percentage_used=pct_used,
                )
                session.add(new_notif)

                if is_breached:
                    limit.last_breach_at = now
                else:
                    limit.last_warning_at = now

                try:
                    await session.flush()
                    notification_id = new_notif.id
                except Exception:
                    logger.opt(exception=True).debug("Notification already exists (race)")

        statuses.append(
            CostLimitStatus(
                cost_limit_id=limit.id,
                scope_type=scope_type_str_val,
                scope_name=scope_name,
                org_id=limit.org_id,
                dept_id=limit.dept_id,
                limit_amount_usd=limit_usd,
                current_cost_usd=round(current_cost, 4),
                percentage_used=pct_used,
                is_warning=is_warning,
                is_breached=is_breached,
                warning_threshold_pct=limit.warning_threshold_pct,
                period_start=period_start,
                period_end=period_end,
                notification_id=notification_id,
                dismissed=dismissed,
            )
        )

    await session.commit()
    return statuses


# ---------------------------------------------------------------------------
# Dismiss notification
# ---------------------------------------------------------------------------


@router.post("/notifications/{notification_id}/dismiss")
async def dismiss_cost_notification(
    notification_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> dict:
    notif = (
        await session.exec(
            select(CostLimitNotification).where(CostLimitNotification.id == notification_id)
        )
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")

    dismissed_ids = list(notif.dismissed_by_user_ids or [])
    if current_user.id not in dismissed_ids:
        dismissed_ids.append(current_user.id)
        notif.dismissed_by_user_ids = dismissed_ids
        await session.commit()

    return {"detail": "Notification dismissed."}
