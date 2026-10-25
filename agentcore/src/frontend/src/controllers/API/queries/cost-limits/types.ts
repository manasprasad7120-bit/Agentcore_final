export interface CostLimitResponse {
  id: string;
  scope_type: "organization" | "department";
  org_id: string;
  org_name: string | null;
  dept_id: string | null;
  dept_name: string | null;
  limit_amount_usd: number;
  currency: string;
  period_type: string;
  period_start_day: number;
  warning_threshold_pct: number;
  action_on_breach: string;
  is_enabled: boolean;
  current_period_cost_usd: number | null;
  last_checked_at: string | null;
  last_breach_at: string | null;
  last_warning_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CostLimitStatus {
  cost_limit_id: string;
  scope_type: "organization" | "department";
  scope_name: string;
  org_id: string;
  dept_id: string | null;
  limit_amount_usd: number;
  current_cost_usd: number;
  percentage_used: number;
  is_warning: boolean;
  is_breached: boolean;
  warning_threshold_pct: number;
  period_start: string;
  period_end: string;
  notification_id: string | null;
  dismissed: boolean;
}

export interface CostLimitCreatePayload {
  scope_type: "organization" | "department";
  org_id: string;
  dept_id?: string | null;
  limit_amount_usd: number;
  warning_threshold_pct?: number;
  period_type?: string;
  period_start_day?: number;
  action_on_breach?: string;
}

export interface CostLimitUpdatePayload {
  limit_amount_usd?: number;
  warning_threshold_pct?: number;
  period_type?: string;
  period_start_day?: number;
  action_on_breach?: string;
  is_enabled?: boolean;
}
