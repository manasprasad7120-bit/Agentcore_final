import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AgentCard } from "./components/AgentCard";
import { Button } from "@/components/ui/button";
import { Globe, Search } from "lucide-react";
import ActionModal from "./components/ActionModal";
import McpConfigModal from "./components/McpConfigModal";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";
import useAlertStore from "@/stores/alertStore";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useDeployPackageRequest, useGetPackageRequestsForApproval } from "@/controllers/API/queries/packages";
import useRegionStore from "@/stores/regionStore";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useGetApprovals, type ApprovalAgent } from "@/controllers/API/queries/approvals";
import { useApprovalActionModal, useApprovalActions } from "./hooks";
import CustomLoader from "@/customization/components/custom-loader";

type FilterType = "all" | "pending" | "approved" | "rejected" | "deployed" | "cancelled";
type ApprovalTabType = "all" | "agent" | "model" | "mcp" | "package";

const APPROVAL_TABS: Array<{ id: ApprovalTabType; label: string; permission: string }> = [
  { id: "agent", label: "AI Agent", permission: "view_agent" },
  { id: "model", label: "Model", permission: "view_model" },
  { id: "mcp", label: "MCP", permission: "view_mcp" },
  { id: "package", label: "Package", permission: "view_packages_page" },
];

export default function ApprovalPage() {
  const { t } = useTranslation();
  /* ================= STATE ================= */
  const [filter, setFilter] = useState<FilterType>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<ApprovalTabType>("all");
  const navigate = useCustomNavigate();
  const { permissions, role } = useContext(AuthContext);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const isRoot = String(role ?? "").toLowerCase() === "root";
  const regions = useRegionStore((s) => s.regions);
  const selectedRegionCode = useRegionStore((s) => s.selectedRegionCode);
  const setSelectedRegion = useRegionStore((s) => s.setSelectedRegion);
  const fetchRegions = useRegionStore((s) => s.fetchRegions);
  const packageRegionCode = isRoot ? selectedRegionCode : null;
  const [isMcpConfigOpen, setIsMcpConfigOpen] = useState(false);
  const [selectedMcpApprovalId, setSelectedMcpApprovalId] = useState<string | null>(null);

  /* ================= MODAL & ACTIONS MANAGEMENT ================= */
  const { isOpen, selectedAgent, action, openModal, closeModal } =
    useApprovalActionModal();
  const { handleApprove, handleReject, isLoading: isActionLoading } = useApprovalActions(packageRegionCode);

  /* ================= API QUERIES ================= */
  // Fetch all approvals from backend
  const { data: agents = [], isLoading: isLoadingAgents } = useGetApprovals();
  const { data: packageRequests = [], isLoading: isLoadingPackageRequests } =
    useGetPackageRequestsForApproval(
      { regionCode: packageRegionCode },
      {
        enabled: isRoot,
      },
    );
  const deployPackageRequestMutation = useDeployPackageRequest();

  useEffect(() => {
    if (isRoot && regions.length === 0) {
      fetchRegions();
    }
  }, [isRoot, regions.length, fetchRegions]);

  const isRemoteRegion =
    isRoot && !!selectedRegionCode && regions.length > 0
      ? (() => {
          const hub = regions.find((region) => region.is_hub);
          return hub ? hub.code !== selectedRegionCode : false;
        })()
      : false;

  const typeTabs = isRoot
    ? APPROVAL_TABS.filter((tab) => tab.id === "package")
    : APPROVAL_TABS.filter((tab) => tab.id !== "package" && can(tab.permission));
  const visibleTabs: Array<{ id: ApprovalTabType; label: string; permission: string }> = [
    { id: "all", label: "All", permission: "" },
    ...typeTabs,
  ];

  useEffect(() => {
    if (visibleTabs.length === 0) return;
    if (!visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab(visibleTabs[0].id);
    }
  }, [activeTab, visibleTabs]);

  useEffect(() => {
    const isPackageLike = activeTab === "package" || (activeTab === "all" && isRoot);
    if (!isPackageLike && (filter === "deployed" || filter === "cancelled")) {
      setFilter("all");
    }
  }, [activeTab, filter, isRoot]);

  /* ================= FILTERING & CALCULATIONS ================= */
  const packageApprovalCards: ApprovalAgent[] = packageRequests.map((request) => ({
    id: request.id,
    entityType: "package",
    title: `${request.package_name}`,
    status: request.status,
    description: request.justification,
    submittedBy: {
      name:
        request.requested_by_name ||
        request.requested_by_email ||
        request.requested_by,
      email: request.requested_by_email ?? null,
    },
    project: request.service_name,
    submitted: request.requested_at,
    version: request.requested_version,
    recentChanges: request.review_comments || request.deployment_notes || "-",
  }));

  const allData = isRoot
    ? packageApprovalCards
    : agents;

  const sourceApprovals =
    activeTab === "all" ? allData :
    activeTab === "package" ? packageApprovalCards :
    agents;

  const filteredAgents = sourceApprovals.filter((agent) => {
    const entityType = (agent.entityType || "agent") as ApprovalTabType;
    const matchesTab = activeTab === "all" ? true : entityType === activeTab;
    const matchesFilter = filter === "all" ? true : agent.status === filter;
    const matchesSearch =
      searchQuery === "" ||
      agent.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (agent.project || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (agent.visibility || "").toLowerCase().includes(searchQuery.toLowerCase());
    return matchesTab && matchesFilter && matchesSearch;
  });

  const pendingCount = allData.filter((a) => a.status === "pending").length;
  const noAgentsMessage =
    filter === "pending"
      ? t("No pending items found")
      : filter === "approved"
        ? t("No approved items found")
        : filter === "rejected"
          ? t("No rejected items found")
          : filter === "deployed"
            ? t("No deployed requests found")
            : filter === "cancelled"
              ? t("No cancelled requests found")
              : t("No items found");

  /* ================= EVENT HANDLERS ================= */
  const handleApproveClick = (agent: ApprovalAgent) => {
    openModal(agent, "approve");
  };

  const handleRejectClick = (agent: ApprovalAgent) => {
    openModal(agent, "reject");
  };

  const handleMcpConfigClick = (agent: ApprovalAgent) => {
    if ((agent.entityType || "agent") !== "mcp") return;
    setSelectedMcpApprovalId(agent.id);
    setIsMcpConfigOpen(true);
  };

  const handlePackageDeploy = async (agent: ApprovalAgent) => {
    await new Promise((resolve, reject) => {
      deployPackageRequestMutation.mutate(
        {
          requestId: agent.id,
          deployment_notes: "Marked as deployed by root",
          regionCode: packageRegionCode,
        },
        {
          onSuccess: () => {
            setSuccessData({ title: `Package "${agent.title}" marked as deployed.`, link: "/approval" });
            resolve(null);
          },
          onError: () => {
            setErrorData({ title: `Failed to mark package "${agent.title}" as deployed.`, link: "/approval" });
            reject(new Error("Package deploy action failed"));
          },
        },
      );
    });
  };

  /**
   * Handle the final action submission from the modal
   * Calls either handleApprove or handleReject based on the action type
   */
  const handleSubmitAction = async (data: {
    comments: string;
    attachments: File[];
  }) => {
    if (!selectedAgent) return;

    if (action === "approve") {
      await handleApprove(selectedAgent, data.comments, data.attachments);
    } else {
      await handleReject(selectedAgent, data.comments, data.attachments);
    }

  };

  return (
    <div className="flex h-full w-full flex-col overflow-auto">
      {/* Header */}
      <div className="flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("Review & Approval")}</h1>
            {pendingCount > 0 && (
              <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300">
                {t("{{count}} pending", { count: pendingCount })}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Review and approve model, MCP, AI agent, and package requests")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isRoot && regions.length > 0 && (
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-muted-foreground" />
              <Select value={selectedRegionCode ?? ""} onValueChange={setSelectedRegion}>
                <SelectTrigger className="w-[220px]">
                  <SelectValue placeholder={t("Select region")} />
                </SelectTrigger>
                <SelectContent>
                  {regions
                    .filter((region) => region.code)
                    .map((region) => (
                      <SelectItem key={region.code} value={region.code}>
                        {region.name}
                        {region.is_hub ? ` (${t("Hub")})` : ""}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {/* Search Bar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder={t("Search agents...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring sm:w-64"
            />
          </div>
        </div>
      </div>

      {isRoot && isRemoteRegion && selectedRegionCode && (
        <div className="border-b border-amber-200 bg-amber-50/70 px-4 py-3 sm:px-6 md:px-8 dark:border-amber-900/30 dark:bg-amber-950/10">
          <p className="text-sm text-amber-800 dark:text-amber-200">
            {t("Viewing and managing package approvals for {{region}} from hub.", {
              region: regions.find((r) => r.code === selectedRegionCode)?.name ?? selectedRegionCode,
            })}
          </p>
        </div>
      )}

      {/* Filter Tabs + Status Tabs */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-6 md:px-8">
        {visibleTabs.map((tab) => (
          <Button
            key={tab.id}
            size="sm"
            variant={activeTab === tab.id ? "default" : "outline"}
            onClick={() => setActiveTab(tab.id)}
          >
            {t(tab.label)}
          </Button>
        ))}

        <div className="h-6 w-px bg-border mx-1" />

        {(activeTab === "package" || (activeTab === "all" && isRoot)
          ? (["all", "pending", "approved", "rejected", "deployed", "cancelled"] as FilterType[])
          : (["all", "pending", "approved", "rejected"] as FilterType[])
        ).map((type) => (
          <Button
            key={type}
            size="sm"
            variant={filter === type ? "default" : "outline"}
            onClick={() => setFilter(type)}
          >
            {t(type.charAt(0).toUpperCase() + type.slice(1))}
          </Button>
        ))}
      </div>

      {/* Agent Cards */}
      <div className="flex-1 overflow-auto p-4 sm:p-6">
        {(isRoot ? isLoadingPackageRequests : isLoadingAgents) ? (
          <div className="flex h-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : (
          <div className="space-y-6">
            {filteredAgents.length === 0 ? (
              <div className="rounded-lg border border-border bg-card p-12 text-center">
                <p className="text-muted-foreground">
                  {searchQuery
                    ? t("No agents found matching your search")
                    : noAgentsMessage}
                </p>
              </div>
            ) : (
              filteredAgents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  {...agent}
                  entityType={agent.entityType}
                  onReject={() => handleRejectClick(agent)}
                  onApprove={() => handleApproveClick(agent)}
                  onReviewDetails={() =>
                    agent.entityType === "mcp"
                      ? setErrorData({ title: t("Use MCP Config for MCP approvals") })
                      : agent.entityType === "package"
                        ? undefined
                      : navigate(`/approval/${agent.id}/review`)
                  }
                  onViewMcpConfig={() => handleMcpConfigClick(agent)}
                  onDeploy={() => handlePackageDeploy(agent)}
                />
              ))
            )}
          </div>
        )}

      </div>

      {/* Action Modal */}
      <ActionModal
        open={isOpen}
        setOpen={closeModal}
        action={action}
        entityType={selectedAgent?.entityType}
        agentTitle={selectedAgent?.title || ""}
        onSubmit={handleSubmitAction}
        isLoading={isActionLoading}
      />
      <McpConfigModal
        open={isMcpConfigOpen}
        setOpen={setIsMcpConfigOpen}
        approvalId={selectedMcpApprovalId}
      />
    </div>
  );
}
