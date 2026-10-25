import { useContext, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import useDragStart from "@/components/core/cardComponent/hooks/use-on-drag-start";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useDeleteAgent from "@/hooks/agents/use-delete-agent";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import ExportModal from "@/modals/exportModal";
import AgentSettingsModal from "@/modals/agentSettingsModal";
import useAlertStore from "@/stores/alertStore";
import { useFolderStore } from "@/stores/foldersStore";
import type { AgentType } from "@/types/agent";
import { downloadAgent } from "@/utils/reactFlowUtils";
import { swatchColors } from "@/utils/styleUtils";
import { cn, getNumberFromString } from "@/utils/utils";
import { useGetPublishStatus } from "@/controllers/API/queries/agents/use-get-publish-status";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { AuthContext } from "@/contexts/authContext";
import useDescriptionModal from "../../hooks/use-description-modal";
import { timeElapsed } from "../../utils/time-elapse";
import DropdownComponent from "../dropdown";
import AgentTransferModal from "../AgentTransferModal";

const ListComponent = ({
  agentData,
  selected,
  setSelected,
  shiftPressed,
  index,
  disabled = false,
  view = "list",
}: {
  agentData: AgentType;
  selected: boolean;
  setSelected: (selected: boolean) => void;
  shiftPressed: boolean;
  index: number;
  disabled?: boolean;
  view?: "grid" | "list";
}) => {
  const navigate = useCustomNavigate();
  const [openDelete, setOpenDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { deleteAgent, isDeleting } = useDeleteAgent();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { folderId } = useParams();
  const [openSettings, setOpenSettings] = useState(false);
  const [openExportModal, setOpenExportModal] = useState(false);
  const [transferMode, setTransferMode] = useState<"move" | "copy" | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const { userData, role } = useContext(AuthContext);
  const folders = useFolderStore((state) => state.folders);
  const currentUserId = String(userData?.id ?? "");
  const normalizedRole = String(role ?? "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const isAdminRole = ["root", "super_admin", "department_admin"].includes(
    normalizedRole,
  );
  const isRestrictedDuplicateRole = ["super_admin", "department_admin"].includes(
    normalizedRole,
  );
  const isComponent = agentData.is_component ?? false;
  const { data: publishStatus } = useGetPublishStatus(
    { agent_id: agentData.id },
    { enabled: !isComponent, refetchInterval: 30000 },
  );
  const workflowLocked = !isComponent && Boolean(publishStatus?.has_pending_approval);
  const effectiveDisabled = disabled || workflowLocked;
  const latestDecision = (publishStatus?.latest_review_decision || "").toUpperCase();
  const latestProdStatus = (publishStatus?.latest_prod_status || "").toUpperCase();
  const requesterId = String(
    publishStatus?.pending_requested_by || publishStatus?.latest_prod_published_by || "",
  );
  const hasDeployment = Boolean(
    publishStatus?.uat?.is_enabled || publishStatus?.prod?.is_enabled,
  );
  const showRequesterBadge = !isComponent && !!requesterId && requesterId === currentUserId;
  const badgeLabel = workflowLocked
    ? "Awaiting Approval"
    : latestProdStatus === "PUBLISHED"
      ? "Approved"
      : latestDecision === "REJECTED"
        ? "Rejected"
        : "";

  const editAgentLink = `/agent/${agentData.id}${folderId ? `/folder/${folderId}` : ""}`;
  const readOnlyAgentLink = `/agent/${agentData.id}${folderId ? `/folder/${folderId}` : ""}?readonly=1`;
  const isAgentOwnedByCurrentUser = agentData.user_id
    ? String(agentData.user_id) === currentUserId
    : false;
  const shouldForceReadOnly = folderId && isAdminRole && !isAgentOwnedByCurrentUser;
  const canModifyAgent = !shouldForceReadOnly;
  const canDuplicateAgent = !isRestrictedDuplicateRole || isAgentOwnedByCurrentUser;
  const canTransferAgent = Boolean(folderId) && isAgentOwnedByCurrentUser;
  const canMoveAgent = canTransferAgent && !hasDeployment;
  const canCopyAgent = canTransferAgent;
  const currentFolder = folderId ? folders?.find((folder) => folder.id === folderId) : undefined;
  const isCreatedByCurrentUser = agentData.created_by_id
    ? String(agentData.created_by_id) === currentUserId
    : isAgentOwnedByCurrentUser || Boolean(currentFolder?.is_own_project);
  const folderCreatorLabel = currentFolder?.is_own_project
    ? "You"
    : currentFolder?.created_by_email?.split("@")[0]?.trim() || "";
  const creatorEmail =
    agentData.created_by_email?.trim() ||
    (currentFolder?.is_own_project ? userData?.email?.trim() : currentFolder?.created_by_email?.trim()) ||
    "";
  const createdByLabel =
    isCreatedByCurrentUser
      ? "You"
      : agentData.created_by?.trim() ||
        agentData.created_by_email?.split("@")[0]?.trim() ||
        folderCreatorLabel;

  const getDeploymentEnvLabel = () => {
    if (publishStatus?.prod?.is_enabled) return "PROD";
    if (publishStatus?.uat?.is_enabled) return "UAT";
    return null;
  };

  const handleOpenTransfer = (mode: "move" | "copy") => {
    if (mode === "move" && hasDeployment) {
      setErrorData({
        title: "Move disabled for UAT/PROD agents",
        list: ["This agent has a UAT/PROD version. Only copying is allowed."],
      });
      return;
    }
    setTransferMode(mode);
    setTransferOpen(true);
  };

  const handleTransferOpenChange = (open: boolean) => {
    setTransferOpen(open);
    if (!open) {
      setTransferMode(null);
    }
  };

  const handleClick = async () => {
    if (effectiveDisabled) return; // Prevent click when disabled
    
    if (shiftPressed) {
      setSelected(!selected);
    } else {
      if (!isComponent) {
        // In project sections, admins should open agents in read-only mode.
        if (shouldForceReadOnly) {
          navigate(readOnlyAgentLink);
          return;
        }
        navigate(editAgentLink);
      }
    }
  };

  const handleDelete = async () => {
    setDeleteError(null);
    const deploymentEnv = getDeploymentEnvLabel();
    if (deploymentEnv) {
      setDeleteError(`This agent is deployed in ${deploymentEnv}.`);
      return;
    }
    try {
      await deleteAgent({ id: [agentData.id] });
      setSuccessData({
        title: "Selected items deleted successfully",
      });
      setOpenDelete(false);
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail || error?.message || "Please try again";
      setDeleteError(detail);
    }
  };

  useEffect(() => {
    if (openDelete) {
      setDeleteError(null);
    }
  }, [openDelete]);

  const { onDragStart } = useDragStart(agentData);

  const descriptionModal = useDescriptionModal(
    [agentData?.id],
    agentData.is_component ? "component" : "agent",
  );

  const swatchIndex =
    (agentData.gradient && !isNaN(parseInt(agentData.gradient))
      ? parseInt(agentData.gradient)
      : getNumberFromString(agentData.gradient ?? agentData.id)) %
    swatchColors.length;

  const handleExport = () => {
    if (agentData.is_component) {
      downloadAgent(agentData, agentData.name, agentData.description);
      setSuccessData({ title: `${agentData.name} exported successfully` });
    } else {
      setOpenExportModal(true);
    }
  };

  /* ── Avatar color derived from agent id ── */
  const PALETTE = [
    "#D04A02", "#1B5FA8", "#2E7D32", "#6A1B9A",
    "#00695C", "#C62828", "#1565C0", "#E65100",
    "#4527A0", "#004D40", "#AD1457", "#0277BD",
  ];
  const avatarColor = (() => {
    let h = 0;
    for (let i = 0; i < agentData.id.length; i++) h = agentData.id.charCodeAt(i) + ((h << 5) - h);
    return PALETTE[Math.abs(h) % PALETTE.length];
  })();
  const avatarInitials = agentData.name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
  const envLabel = getDeploymentEnvLabel();

  /* ── Reusable actions dropdown ── */
  const actionsMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={effectiveDisabled}>
        <Button
          variant="ghost"
          size="iconMd"
          data-testid="home-dropdown-menu"
          onClick={(e) => e.stopPropagation()}
          className="opacity-0 transition-opacity group-hover:opacity-100"
          disabled={effectiveDisabled}
        >
          <ForwardedIconComponent name="Ellipsis" aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-[185px]" sideOffset={5} side="bottom">
        <DropdownComponent
          agentData={agentData}
          setOpenDelete={setOpenDelete}
          handleExport={handleExport}
          handleEdit={() => setOpenSettings(true)}
          canModifyAgent={canModifyAgent}
          canDuplicateAgent={canDuplicateAgent}
          canCopyAgent={canCopyAgent}
          canMoveAgent={canMoveAgent}
          onCopyToProject={() => handleOpenTransfer("copy")}
          onMoveToProject={() => handleOpenTransfer("move")}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );

  /* ══════════════ GRID CARD ══════════════ */
  if (view === "grid") {
    return (
      <>
        <div
          key={agentData.id}
          draggable={!effectiveDisabled}
          onDragStart={effectiveDisabled ? undefined : onDragStart}
          onClick={handleClick}
          data-testid="list-card"
          className={cn(
            "group relative flex h-full flex-col gap-3 overflow-hidden rounded-2xl border border-border bg-card p-4",
            "transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_12px_32px_-14px_rgba(0,0,0,0.22)]",
            isComponent || effectiveDisabled ? "cursor-default" : "cursor-pointer",
            effectiveDisabled && "opacity-60",
          )}
          style={selected ? { boxShadow: `0 0 0 2px ${avatarColor}` } : undefined}
        >
          {/* top accent bar on hover */}
          <div
            className="pointer-events-none absolute inset-x-0 top-0 h-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
            style={{ background: avatarColor }}
          />

          {/* header: avatar + checkbox/menu */}
          <div className="flex items-start justify-between">
            <div className="relative flex-shrink-0">
              <div
                className="flex h-11 w-11 items-center justify-center rounded-xl text-sm font-bold text-white shadow-sm"
                style={{ background: `linear-gradient(135deg, ${avatarColor} 0%, ${avatarColor}CC 100%)` }}
              >
                {avatarInitials}
              </div>
              {envLabel && (
                <span
                  className={cn(
                    "absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-card",
                    envLabel === "PROD" ? "bg-emerald-500" : "bg-amber-400",
                  )}
                />
              )}
            </div>
            <div className="flex items-center gap-1">
              <div className={cn("transition-opacity", selected ? "opacity-100" : "opacity-0 group-hover:opacity-100")}>
                <Checkbox
                  checked={selected}
                  onCheckedChange={(v) => setSelected(v as boolean)}
                  onClick={(e) => e.stopPropagation()}
                  disabled={effectiveDisabled}
                  className="focus-visible:ring-0"
                  data-testid={`checkbox-${agentData.id}`}
                />
              </div>
              {actionsMenu}
            </div>
          </div>

          {/* name + pills */}
          <div className="flex flex-col gap-1.5">
            <span className="truncate text-sm font-semibold text-foreground" data-testid={`agent-name-${agentData.id}`}>
              {agentData.name}
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              {showRequesterBadge && !!badgeLabel && (
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-semibold leading-4",
                    workflowLocked && "bg-yellow-100 text-yellow-800",
                    !workflowLocked && latestProdStatus === "PUBLISHED" && "bg-green-100 text-green-800",
                    !workflowLocked && latestDecision === "REJECTED" && "bg-red-100 text-red-800",
                  )}
                >
                  {badgeLabel}
                </span>
              )}
              {envLabel && !showRequesterBadge && (
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-semibold",
                    envLabel === "PROD" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-700",
                  )}
                >
                  {envLabel}
                </span>
              )}
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                style={{ background: `${avatarColor}12`, color: avatarColor }}
              >
                {isComponent ? "Component" : "Agent"}
              </span>
            </div>
          </div>

          {/* description */}
          <p className="line-clamp-2 min-h-[2rem] text-xs leading-relaxed text-muted-foreground" title={agentData.description || undefined}>
            {agentData.description?.trim() || "No description provided."}
          </p>

          {/* tags */}
          {(agentData.tags ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1">
              {(agentData.tags ?? []).slice(0, 3).map((tag) => (
                <span
                  key={tag}
                  className="rounded-md border border-border/50 bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
              {(agentData.tags ?? []).length > 3 && (
                <span className="rounded-md border border-border/50 bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                  +{(agentData.tags ?? []).length - 3}
                </span>
              )}
            </div>
          )}

          {/* footer */}
          <div className="mt-auto flex items-center justify-between border-t border-border/60 pt-3">
            <div className="flex min-w-0 items-center gap-2">
              {createdByLabel && (
                <>
                  <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground">
                    {createdByLabel.slice(0, 2).toUpperCase()}
                  </div>
                  <span className="truncate text-xs text-muted-foreground" title={creatorEmail || undefined}>
                    {createdByLabel}
                  </span>
                </>
              )}
            </div>
            <span className="flex-shrink-0 whitespace-nowrap text-xs text-muted-foreground/60">
              {timeElapsed(agentData.updated_at)} ago
            </span>
          </div>
        </div>

        {openDelete && (
          <DeleteConfirmationModal
            open={openDelete}
            setOpen={setOpenDelete}
            onConfirm={handleDelete}
            description={descriptionModal}
            note={!agentData.is_component ? "and its message history" : ""}
            errorMessage={deleteError ?? undefined}
            closeOnConfirm={false}
            loading={isDeleting}
          />
        )}
        <ExportModal open={openExportModal} setOpen={setOpenExportModal} agentData={agentData} />
        <AgentSettingsModal open={openSettings} setOpen={setOpenSettings} agentData={agentData} />
        {transferMode && (
          <AgentTransferModal
            open={transferOpen}
            setOpen={handleTransferOpenChange}
            mode={transferMode}
            agent={agentData}
            currentProjectId={folderId}
            deploymentWarning={hasDeployment}
          />
        )}
      </>
    );
  }

  /* ══════════════ LIST ROW ══════════════ */
  return (
    <>
      <Card
        key={agentData.id}
        draggable={!effectiveDisabled}
        onDragStart={effectiveDisabled ? undefined : onDragStart}
        onClick={handleClick}
        className={cn(
          "flex flex-row bg-background group justify-between rounded-lg border-none px-4 py-3 shadow-none hover:bg-muted",
          isComponent ? "cursor-default" : effectiveDisabled ? "cursor-not-allowed" : "cursor-pointer",
          effectiveDisabled && "opacity-70"
        )}
        data-testid="list-card"
      >
        <div
          className={`flex min-w-0 ${
            isComponent ? "cursor-default" : effectiveDisabled ? "cursor-not-allowed" : "cursor-pointer"
          } items-center gap-4`}
        >
          <div className="group/checkbox relative flex items-center">
            <div
              className={cn(
                "z-20 flex w-0 items-center transition-all duration-300",
                selected && "w-10",
              )}
            >
              <Checkbox
                checked={selected}
                onCheckedChange={(checked) => setSelected(checked as boolean)}
                onClick={(e) => e.stopPropagation()}
                disabled={effectiveDisabled}
                className={cn(
                  "ml-2 transition-opacity focus-visible:ring-0",
                  !selected && "opacity-0 group-hover/checkbox:opacity-100",
                )}
                data-testid={`checkbox-${agentData.id}`}
              />
            </div>
            <div
              className={cn(
                "flex items-center justify-center rounded-lg p-1.5",
                index % 2 === 0 ? "bg-muted-foreground/30" : "bg-[var(--info-foreground)]",
              )}
            >
              <ForwardedIconComponent
                name="Workagent"
                className={cn(
                  "h-5 w-5",
                  index % 2 === 0 ? "text-foreground" : "text-white",
                )}
              />
            </div>
          </div>

          <div className="flex min-w-0 flex-col justify-start">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
              <div
                className="flex min-w-0 flex-shrink truncate text-sm font-semibold"
                data-testid={`agent-name-div`}
              >
                <span
                  className="truncate"
                  data-testid={`agent-name-${agentData.id}`}
                >
                  {agentData.name}
                </span>
              </div>
              <div className="flex min-w-0 flex-shrink text-xs text-muted-foreground">
                <span className="truncate">
                  Edited {timeElapsed(agentData.updated_at)} ago
                </span>
              </div>
              {showRequesterBadge && !!badgeLabel && (
                <ShadTooltip
                  content={
                    workflowLocked
                      ? "PROD request is awaiting approval."
                      : latestDecision === "REJECTED"
                        ? "Your PROD publish request was rejected."
                        : latestProdStatus === "PUBLISHED"
                          ? "Your PROD publish request is approved."
                          : ""
                  }
                >
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[11px] font-medium leading-4",
                      workflowLocked && "bg-yellow-100 text-yellow-800",
                      !workflowLocked &&
                        latestProdStatus === "PUBLISHED" &&
                        "bg-green-100 text-green-800",
                      !workflowLocked &&
                        latestDecision === "REJECTED" &&
                        "bg-red-100 text-red-800",
                    )}
                  >
                    {badgeLabel}
                  </span>
                </ShadTooltip>
              )}
            </div>
            {(agentData.description?.trim() || (agentData.tags ?? []).length > 0) && (
              <div className="mt-1 flex min-w-0 flex-col gap-2">
                {agentData.description?.trim() && (
                  <p
                    className="max-w-[36rem] truncate text-xs leading-5 text-muted-foreground"
                    title={agentData.description}
                  >
                    {agentData.description}
                  </p>
                )}
                {(agentData.tags ?? []).length > 0 && (
                  <div
                    className="relative flex min-w-0 flex-wrap gap-1.5 group/tags"
                    title={agentData.tags?.join(", ") || undefined}
                  >
                    {(agentData.tags ?? []).slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex max-w-[120px] items-center rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
                        title={tag}
                      >
                        <span className="truncate">{tag}</span>
                      </span>
                    ))}
                    {(agentData.tags ?? []).length > 3 && (
                      <span
                        className="inline-flex items-center rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
                        title={agentData.tags?.join(", ") || undefined}
                      >
                        +{(agentData.tags ?? []).length - 3}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="ml-5 flex items-center gap-3">
          {createdByLabel && (
            <div className="hidden min-w-0 items-center gap-2 text-xs text-muted-foreground sm:flex">
              <span className="whitespace-nowrap">Created by</span>
              <div className="flex min-w-0 items-center gap-2">
                <span
                  className="max-w-[96px] truncate font-medium text-foreground"
                  title={creatorEmail || undefined}
                >
                  {createdByLabel}
                </span>
              </div>
            </div>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild disabled={effectiveDisabled}>
              <Button
                variant="ghost"
                size="iconMd"
                data-testid="home-dropdown-menu"
                className="group"
                disabled={effectiveDisabled}
              >
                <ForwardedIconComponent
                  name="Ellipsis"
                  aria-hidden="true"
                  className="h-5 w-5 text-muted-foreground group-hover:text-foreground"
                />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="w-[185px]"
              sideOffset={5}
              side="bottom"
            >
              <DropdownComponent
                agentData={agentData}
                setOpenDelete={setOpenDelete}
                handleExport={handleExport}
                handleEdit={() => {
                  setOpenSettings(true);
                }}
                canModifyAgent={canModifyAgent}
                canDuplicateAgent={canDuplicateAgent}
                canCopyAgent={canCopyAgent}
                canMoveAgent={canMoveAgent}
                onCopyToProject={() => handleOpenTransfer("copy")}
                onMoveToProject={() => handleOpenTransfer("move")}
              />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Card>
      {openDelete && (
        <DeleteConfirmationModal
          open={openDelete}
          setOpen={setOpenDelete}
          onConfirm={handleDelete}
          description={descriptionModal}
          note={!agentData.is_component ? "and its message history" : ""}
          errorMessage={deleteError ?? undefined}
          closeOnConfirm={false}
          loading={isDeleting}
        />
      )}
      <ExportModal
        open={openExportModal}
        setOpen={setOpenExportModal}
        agentData={agentData}
      />
      <AgentSettingsModal
        open={openSettings}
        setOpen={setOpenSettings}
        agentData={agentData}
      />
      {transferMode && (
        <AgentTransferModal
          open={transferOpen}
          setOpen={handleTransferOpenChange}
          mode={transferMode}
          agent={agentData}
          currentProjectId={folderId}
          deploymentWarning={hasDeployment}
        />
      )}
    </>
  );
};

export default ListComponent;
