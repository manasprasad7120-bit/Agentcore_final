import { useContext } from "react";
import { useTranslation } from "react-i18next";
import IconComponent from "@/components/common/genericIconComponent";
import { useGetCostLimitStatus } from "@/controllers/API/queries/cost-limits/use-get-cost-limit-status";
import type { CostLimitStatus } from "@/controllers/API/queries/cost-limits/types";
import { AuthContext } from "@/contexts/authContext";

function formatCurrency(val: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(val);
}

function AlertItem({ status }: { status: CostLimitStatus }) {
  const { t } = useTranslation();
  const isBreach = status.is_breached;
  const scopeLabel =
    status.scope_type === "organization" ? t("Organization") : t("Department");

  const bgClass = isBreach
    ? "bg-red-50 border-l-4 border-red-400"
    : "bg-amber-50 border-l-4 border-amber-400";
  const textClass = isBreach ? "text-red-800" : "text-amber-800";
  const iconName = isBreach ? "XCircle" : "AlertTriangle";

  const message = isBreach
    ? t("COST LIMIT EXCEEDED: {{scope}} '{{name}}' has exceeded its {{limit}} monthly cost limit ({{cost}} used).", {
        scope: scopeLabel,
        name: status.scope_name,
        limit: formatCurrency(status.limit_amount_usd),
        cost: formatCurrency(status.current_cost_usd),
      })
    : t("{{scope}} '{{name}}' has used {{pct}}% of its {{limit}} monthly cost limit ({{cost}} used).", {
        scope: scopeLabel,
        name: status.scope_name,
        pct: status.percentage_used.toFixed(1),
        limit: formatCurrency(status.limit_amount_usd),
        cost: formatCurrency(status.current_cost_usd),
      });

  return (
    <div className={`flex items-center px-4 py-2.5 ${bgClass}`}>
      <div className={`flex items-center gap-2 ${textClass}`}>
        <IconComponent name={iconName} className="h-4 w-4 flex-shrink-0" />
        <span className="text-sm font-medium">{message}</span>
      </div>
    </div>
  );
}

export default function CostLimitBanner() {
  const { role } = useContext(AuthContext);

  const normalizedRole = (role ?? "").toLowerCase();
  const isAdmin = normalizedRole === "root" || normalizedRole === "super_admin" || normalizedRole === "department_admin";
  const { data: statuses } = useGetCostLimitStatus(isAdmin);

  if (!isAdmin || !statuses || statuses.length === 0) {
    return null;
  }

  // Show all warnings and breaches — banner persists until the cost limit is modified or deleted
  const activeAlerts = statuses.filter(
    (s) => s.is_warning || s.is_breached,
  );

  if (activeAlerts.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col">
      {activeAlerts.map((status) => (
        <AlertItem key={status.cost_limit_id} status={status} />
      ))}
    </div>
  );
}
