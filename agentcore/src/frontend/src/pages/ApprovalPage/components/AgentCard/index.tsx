import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, FileCode2 } from "lucide-react";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { useTranslation } from "react-i18next";

interface AgentCardProps {
  id: string;
  entityType?: "agent" | "model" | "mcp" | "package";
  title: string;
  status: "pending" | "approved" | "rejected" | "deployed" | "cancelled";
  description: string;
  submittedBy: {
    name: string;
    avatar?: string;
    email?: string | null;
  };
  approver?: {
    id?: string | null;
    name: string;
    email?: string | null;
    role?: string | null;
  } | null;
  project?: string;
  visibility?: string | null;
  submitted: string;
  version: string;
  recentChanges: string;
  onReject: () => void;
  onApprove: () => void;
  onReviewDetails: () => void;
  onViewMcpConfig?: () => void;
  onDeploy?: () => void;
}

const ENTITY_BADGE_CLASSES: Record<string, string> = {
  model: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  mcp: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  package: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
};

const ENTITY_LABELS: Record<string, string> = {
  model: "Model",
  mcp: "MCP",
  package: "Package",
};

export function AgentCard({
  entityType = "agent",
  title,
  status,
  description,
  submittedBy,
  approver,
  project,
  visibility,
  submitted,
  version,
  recentChanges,
  onReject,
  onApprove,
  onReviewDetails,
  onViewMcpConfig,
  onDeploy,
}: AgentCardProps) {
  const { t } = useTranslation();

  const statusColors = {
    pending:
      "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    approved:
      "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    rejected: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    deployed:
      "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    cancelled: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  };

  const { permissions, userData } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const currentUserId = String(userData?.id ?? "");
  const approverNameRaw = approver?.name?.trim() ?? "";
  const approverEmail = approver?.email?.trim() ?? "";
  const approverDisplayName = (() => {
    if (approverNameRaw && !approverNameRaw.includes("@")) return approverNameRaw;
    if (approverEmail) return approverEmail.split("@", 1)[0];
    if (approverNameRaw) {
      const atIndex = approverNameRaw.indexOf("@");
      return atIndex > 0 ? approverNameRaw.slice(0, atIndex) : approverNameRaw;
    }
    return t("Unknown");
  })();
  const isApproverYou =
    approver?.id && String(approver.id) === currentUserId && currentUserId !== "";
  const approverLabel = approver
    ? isApproverYou
      ? t("You")
      : approverDisplayName
    : "";
  const canModerate = entityType === "package" ? true : can("view_approval_page");
  const submittedDisplay = (() => {
    const dt = new Date(submitted);
    if (Number.isNaN(dt.getTime())) return submitted;
    return dt.toLocaleString();
  })();
  const submittedByDisplay = (() => {
    const raw = submittedBy?.name?.trim() ?? "";
    const explicit = submittedBy?.email?.trim() ?? "";
    if (raw && !raw.includes("@")) return raw;
    if (explicit) return explicit.split("@", 1)[0];
    if (!raw) return t("Unknown");
    const atIndex = raw.indexOf("@");
    return atIndex > 0 ? raw.slice(0, atIndex) : raw;
  })();
  const submittedByEmail = (() => {
    const explicit = submittedBy?.email?.trim() ?? "";
    if (explicit) return explicit;
    const raw = submittedBy?.name?.trim() ?? "";
    return raw.includes("@") ? raw : "";
  })();
  const projectDisplay = project?.trim() ?? "";
  const visibilityDisplay = visibility?.trim() ?? "";
  const metadataItems = [
    {
      key: "submitted-by",
      label: t("Submitted By"),
      content: submittedByEmail ? (
        <ShadTooltip content={submittedByEmail}>
          <div className="truncate font-medium">{submittedByDisplay}</div>
        </ShadTooltip>
      ) : (
        <div className="truncate font-medium">{submittedByDisplay}</div>
      ),
    },
    ...(entityType !== "package" && entityType !== "mcp" && projectDisplay
      ? [
          {
            key: "project",
            label: t("Project"),
            content: <div className="font-medium">{projectDisplay}</div>,
          },
        ]
      : []),
    ...((entityType === "model" || entityType === "mcp") && visibilityDisplay
      ? [
          {
            key: "visibility",
            label: t("Visibility"),
            content: <div className="font-medium">{visibilityDisplay}</div>,
          },
        ]
      : []),
    {
      key: "version",
      label: t("Version"),
      content: <div className="font-medium">{version || "-"}</div>,
    },
    {
      key: "submitted",
      label: t("Submitted"),
      content: <div className="font-medium">{submittedDisplay}</div>,
    },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-6 transition-shadow hover:shadow-md">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between">
        <div className="flex-1">
          <div className="mb-2 flex items-center gap-3">
            <h3 className="text-lg font-semibold">{title}</h3>
            {entityType && entityType !== "agent" && (
              <span
                className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  ENTITY_BADGE_CLASSES[entityType] ?? ""
                }`}
              >
                {t(ENTITY_LABELS[entityType] ?? entityType)}
              </span>
            )}
            <span
              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${statusColors[status]}`}
            >
              {t(status.charAt(0).toUpperCase() + status.slice(1))}
            </span>
            {approverLabel && status !== "pending" && (
              approverEmail ? (
                <ShadTooltip content={approverEmail}>
                  <span className="inline-flex rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                    {t("by")} {approverLabel}
                  </span>
                </ShadTooltip>
              ) : (
                <span className="inline-flex rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                  {t("by")} {approverLabel}
                </span>
              )
            )}
          </div>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </div>

      {/* Metadata */}
      <div className="mb-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
        {metadataItems.map((item) => (
          <div key={item.key} className="min-w-0">
            <div className="text-xs text-muted-foreground">{item.label}</div>
            {item.content}
          </div>
        ))}
      </div>

      {/* Recent Changes - hidden for models */}
      {entityType !== "model" && entityType !== "package" && entityType !== "mcp" && (
        <div className="mb-4 rounded-md bg-muted/50 p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("Recent Changes")}
          </div>
          <div className="text-sm font-medium">{recentChanges}</div>
        </div>
      )}

      {/* Actions */}
      {/* Actions */}
      <div className="flex w-full items-center gap-2">
        {/* LEFT actions */}
        <div className="flex flex-wrap items-center gap-2">
          {entityType === "mcp" ? (
            <Button variant="outline" onClick={onViewMcpConfig} className="gap-2">
              <FileCode2 className="h-4 w-4" />
              {t("Review Details")}
            </Button>
          ) : entityType === "package" ? null : (
            <Button variant="outline" onClick={onReviewDetails} className="gap-2">
              <FileCode2 className="h-4 w-4" />
              {t("Review Details")}
            </Button>
          )}
        </div>

        {/* RIGHT actions */}
        {status === "pending" && (
          <div className="ml-auto flex items-center gap-2">
<ShadTooltip 
  content={!canModerate ? t("You don't have permission to reject") : ""}
>
  <span className="inline-block">
    <Button
      variant="outline"
      onClick={onReject}
      disabled={!canModerate}
      className="
        gap-2
        border-red-500 text-red-600
        hover:!bg-red-50 hover:!text-red-600
        dark:border-red-700 dark:text-red-400
        dark:hover:!bg-red-950/30 dark:hover:!text-red-400
      "
    >
      <XCircle className="h-4 w-4" />
      {t("Reject")}
    </Button>
  </span>
</ShadTooltip>
           
<ShadTooltip 
  content={!canModerate ? t("You don't have permission to approve") : ""}
>
            <Button
              variant="outline"
              onClick={onApprove}
              className="
    gap-2
    !border-green-700 text-green-600
    hover:!border-green-700 focus-visible:!border-green-700
    disabled:!border-green-700 disabled:!opacity-100
    hover:!bg-green-50 hover:!text-green-600
    dark:border-green-700 dark:text-green-400
    dark:hover:!border-green-700 dark:focus-visible:!border-green-700
    dark:disabled:!border-green-700
    dark:hover:!bg-green-950/30 dark:hover:!text-green-400
  "
  disabled={!canModerate}
            >
              <CheckCircle2 className="h-4 w-4" />
              {t("Approve")}
            </Button>
          </ShadTooltip>
          </div>
        )}
        {status === "approved" && entityType === "package" && (
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              onClick={onDeploy}
              className="gap-2 border-blue-600 text-blue-600 hover:bg-blue-50"
            >
              <CheckCircle2 className="h-4 w-4" />
              {t("Mark Deployed")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
