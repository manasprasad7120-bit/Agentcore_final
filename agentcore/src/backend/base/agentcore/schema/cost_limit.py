from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CostLimitCreate(BaseModel):
    scope_type: str = Field(..., pattern="^(organization|department)$")
    org_id: UUID
    dept_id: UUID | None = None
    limit_amount_usd: float = Field(..., gt=0, le=1_000_000)
    warning_threshold_pct: int = Field(default=80, ge=1, le=100)
    period_type: str = Field(default="monthly", pattern="^(monthly|quarterly|custom)$")
    period_start_day: int = Field(default=1, ge=1, le=28)
    action_on_breach: str = Field(default="notify_only", pattern="^(notify_only|notify_and_block)$")


class CostLimitUpdate(BaseModel):
    limit_amount_usd: float | None = Field(default=None, gt=0, le=1_000_000)
    warning_threshold_pct: int | None = Field(default=None, ge=1, le=100)
    period_type: str | None = Field(default=None, pattern="^(monthly|quarterly|custom)$")
    period_start_day: int | None = Field(default=None, ge=1, le=28)
    action_on_breach: str | None = Field(default=None, pattern="^(notify_only|notify_and_block)$")
    is_enabled: bool | None = None


class CostLimitResponse(BaseModel):
    id: UUID
    scope_type: str
    org_id: UUID
    org_name: str | None = None
    dept_id: UUID | None = None
    dept_name: str | None = None
    limit_amount_usd: float
    currency: str
    period_type: str
    period_start_day: int
    warning_threshold_pct: int
    action_on_breach: str
    is_enabled: bool
    current_period_cost_usd: float | None = None
    last_checked_at: datetime | None = None
    last_breach_at: datetime | None = None
    last_warning_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CostLimitStatus(BaseModel):
    cost_limit_id: UUID
    scope_type: str
    scope_name: str
    org_id: UUID
    dept_id: UUID | None = None
    limit_amount_usd: float
    current_cost_usd: float
    percentage_used: float
    is_warning: bool
    is_breached: bool
    warning_threshold_pct: int
    period_start: datetime
    period_end: datetime
    notification_id: UUID | None = None
    dismissed: bool = False
