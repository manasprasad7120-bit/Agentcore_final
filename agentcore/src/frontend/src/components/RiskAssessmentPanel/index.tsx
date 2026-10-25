import { AlertTriangle, CheckCircle2, Info, ShieldAlert } from "lucide-react";
import type {
  McpRiskAnalysisResponse,
  McpRiskFinding,
  McpRiskOverall,
  McpRiskSeverity,
} from "@/types/mcp";
import { cn } from "@/utils/utils";

type Props = {
  analysis: McpRiskAnalysisResponse | null;
  isLoading?: boolean;
  compact?: boolean;
  emptyMessage?: string;
};

const overallStyle: Record<
  McpRiskOverall,
  { label: string; classes: string; Icon: typeof ShieldAlert }
> = {
  high_risk: {
    label: "HIGH RISK",
    classes:
      "bg-red-100 text-red-800 border-red-300 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800",
    Icon: ShieldAlert,
  },
  review_carefully: {
    label: "REVIEW CAREFULLY",
    classes:
      "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800",
    Icon: AlertTriangle,
  },
  looks_ok: {
    label: "LOOKS OK",
    classes:
      "bg-green-100 text-green-800 border-green-300 dark:bg-green-950/40 dark:text-green-300 dark:border-green-800",
    Icon: CheckCircle2,
  },
};

const severityStyle: Record<
  McpRiskSeverity,
  { rowClasses: string; iconClasses: string; Icon: typeof ShieldAlert; label: string }
> = {
  high: {
    rowClasses:
      "border-red-300 bg-red-50/60 dark:border-red-900 dark:bg-red-950/30",
    iconClasses: "text-red-600 dark:text-red-400",
    Icon: ShieldAlert,
    label: "HIGH",
  },
  medium: {
    rowClasses:
      "border-amber-300 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30",
    iconClasses: "text-amber-600 dark:text-amber-400",
    Icon: AlertTriangle,
    label: "MED",
  },
  low: {
    rowClasses:
      "border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-950/30",
    iconClasses: "text-slate-500 dark:text-slate-400",
    Icon: Info,
    label: "LOW",
  },
};

function FindingRow({ finding }: { finding: McpRiskFinding }) {
  const style = severityStyle[finding.severity];
  const { Icon } = style;
  return (
    <div className={cn("flex items-start gap-2 rounded-md border p-2.5", style.rowClasses)}>
      <Icon className={cn("mt-0.5 h-4 w-4 flex-shrink-0", style.iconClasses)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide", style.iconClasses)}>
            {style.label}
          </span>
          <span className="text-xs uppercase tracking-wide opacity-70">
            {finding.category}
          </span>
          <span className="truncate">{finding.title}</span>
        </div>
        <div className="mt-1 text-xs opacity-90">{finding.detail}</div>
        {finding.recommendation && (
          <div className="mt-1 text-xs italic opacity-80">
            {finding.recommendation}
          </div>
        )}
      </div>
    </div>
  );
}

export default function RiskAssessmentPanel({
  analysis,
  isLoading = false,
  compact = false,
  emptyMessage,
}: Props) {
  if (isLoading && !analysis) {
    return (
      <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        Analysing configuration...
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        {emptyMessage ?? "No analysis yet."}
      </div>
    );
  }

  const overall = overallStyle[analysis.overall];
  const { Icon } = overall;

  return (
    <div className="flex flex-col gap-2">
      <div
        className={cn(
          "flex items-center justify-between gap-2 rounded-md border px-3 py-2",
          overall.classes,
        )}
      >
        <div className="flex items-center gap-2 font-semibold">
          <Icon className="h-4 w-4" />
          <span>{overall.label}</span>
        </div>
        <div className="flex items-center gap-3 text-xs font-medium">
          <span>HIGH: {analysis.high_count}</span>
          <span>MED: {analysis.medium_count}</span>
          <span>LOW: {analysis.low_count}</span>
        </div>
      </div>
      {analysis.findings.length === 0 ? (
        <div className="rounded-md border border-dashed p-2 text-xs text-muted-foreground">
          No specific findings - configuration looks routine.
        </div>
      ) : (
        <div className={cn("flex flex-col gap-1.5", compact ? "max-h-72 overflow-auto pr-1" : "")}>
          {analysis.findings.map((f) => (
            <FindingRow key={f.rule_id + ":" + f.title} finding={f} />
          ))}
        </div>
      )}
    </div>
  );
}
