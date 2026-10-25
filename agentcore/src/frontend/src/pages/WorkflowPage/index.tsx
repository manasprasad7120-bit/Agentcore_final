import { ArrowUpToLine, Filter, Info, Search, Share2, X } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useGetPublishDepartments } from "@/controllers/API/queries/agents/use-get-publish-departments";
import { useGetPublishEmailSuggestions } from "@/controllers/API/queries/agents/use-get-publish-email-suggestions";
import { useValidatePublishEmail } from "@/controllers/API/queries/agents/use-validate-publish-email";
import {
  useGetControlPanelAgentSharing,
  useGetControlPanelAgents,
  usePostControlPanelPromote,
  usePutControlPanelAgentSharing,
  useToggleControlPanelAgent,
} from "@/controllers/API/queries/control-panel";
import { useGetAllTriggers } from "@/controllers/API/queries/triggers/use-get-all-triggers";
import CustomLoader from "@/customization/components/custom-loader";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import EmbedModal from "@/modals/EmbedModal/embed-modal";
import ExportApiModal from "@/modals/exportApiModal";
import ExportModal from "@/modals/exportModal";
import useAlertStore from "@/stores/alertStore";
import type { AgentType } from "@/types/agent";
import SchedulerPage from "@/pages/SchedulerPage";

type EnvironmentTab = "UAT" | "PROD";
type FilterTab = "creator" | "owner" | "department" | "version" | "deployment" | "timeline";
type CreatedDateFilter = "all" | "today" | "7d" | "30d" | "90d";

interface WorkagentType {
  id: string;
  agentId?: string;
  name: string;
  description: string;
  version?: string;
  runVersion?: string;
  environment?: "uat" | "prod";
  visibility?: "PUBLIC" | "PRIVATE" | string;
  user: string;
  userEmail?: string;
  owner?: string;
  ownerCount?: number;
  ownerNames?: string[];
  ownerEmails?: string[];
  department: string;
  created: string;
  createdAtRaw?: string;
  movedToProd?: boolean;
  pendingProdApproval?: boolean;
  status: boolean;
  enabled: boolean;
  inputType?: "chat" | "autonomous" | "file_processing";
}

const EMPTY_WORKFLOWS: WorkagentType[] = [];

interface WorkflowsViewProps {
  workflows?: WorkagentType[];
  setSearch?: (search: string) => void;
  onWorkagentClick?: (workflow: WorkagentType) => void;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

export default function WorkflowsView({
  workflows = EMPTY_WORKFLOWS,
  setSearch,
  onWorkagentClick,
}: WorkflowsViewProps): JSX.Element {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<EnvironmentTab>("UAT");
  const [showFilters, setShowFilters] = useState(false);
  const [activeFilterTab, setActiveFilterTab] = useState<FilterTab>("creator");
  const [selectedCreator, setSelectedCreator] = useState("all");
  const [selectedOwner, setSelectedOwner] = useState("all");
  const [selectedDepartment, setSelectedDepartment] = useState("all");
  const [selectedVersion, setSelectedVersion] = useState("all");
  const [selectedEnabledState, setSelectedEnabledState] = useState("all");
  const [selectedStartStopState, setSelectedStartStopState] = useState("all");
  const [selectedCreatedDate, setSelectedCreatedDate] =
    useState<CreatedDateFilter>("all");
  const [workflowStates, setWorkagentStates] = useState<{
    [key: string]: { status: boolean; enabled: boolean };
  }>({});
  const [pendingToggles, setPendingToggles] = useState<{
    [key: string]: { status: boolean; enabled: boolean };
  }>({});
  // Pending confirmation for Start/Stop or Enable/Disable. Set when the user
  // clicks a toggle; the actual mutation only fires after they confirm.
  const [toggleConfirm, setToggleConfirm] = useState<{
    workflowId: string;
    kind: "status" | "enabled";
    nextValue: boolean;
    agentName: string;
  } | null>(null);
  const [selectedSharingAgentId, setSelectedSharingAgentId] =
    useState<string>("");
  const [selectedSharingAgentName, setSelectedSharingAgentName] =
    useState<string>("");
  const [selectedSharingEnvironment, setSelectedSharingEnvironment] =
    useState<"uat" | "prod">("uat");
  const [selectedSharingVersion, setSelectedSharingVersion] =
    useState<string>("");
  const [selectedSharingDeployId, setSelectedSharingDeployId] =
    useState<string>("");
  const [sharingDialogOpen, setSharingDialogOpen] = useState(false);
  const [sharingSelectedEmails, setSharingSelectedEmails] = useState<string[]>(
    [],
  );
  const [sharingEmailDraft, setSharingEmailDraft] = useState("");
  const [debouncedSharingEmailQuery, setDebouncedSharingEmailQuery] =
    useState("");
  const [sharingRecipientsInitialized, setSharingRecipientsInitialized] =
    useState(false);
  const [savingSharing, setSavingSharing] = useState(false);
  const [promotingById, setPromotingById] = useState<Record<string, boolean>>(
    {},
  );
  const [promoteDialogOpen, setPromoteDialogOpen] = useState(false);
  const [selectedPromoteDeployId, setSelectedPromoteDeployId] =
    useState<string>("");
  const [selectedPromoteAgentId, setSelectedPromoteAgentId] =
    useState<string>("");
  const [selectedPromoteVisibility, setSelectedPromoteVisibility] = useState<
    "PRIVATE" | "PUBLIC"
  >("PRIVATE");
  const [promoteSelectedEmails, setPromoteSelectedEmails] = useState<string[]>(
    [],
  );
  const [promoteEmailDraft, setPromoteEmailDraft] = useState("");
  const [debouncedPromoteEmailQuery, setDebouncedPromoteEmailQuery] =
    useState("");
  const [promoteRecipientsInitialized, setPromoteRecipientsInitialized] =
    useState(false);
  const [selectedPromoteDepartmentId, setSelectedPromoteDepartmentId] =
    useState<string>("");
  const [openExportModal, setOpenExportModal] = useState(false);
  const [openEmbedModal, setOpenEmbedModal] = useState(false);
  const [openExportApiModal, setOpenExportApiModal] = useState(false);
  const [schedulerAgent, setSchedulerAgent] = useState<WorkagentType | null>(
    null,
  );
  const [exportApiAgent, setExportApiAgent] = useState<{
    agentId: string;
    agentName: string;
    version: string;
    deployId: string;
  } | null>(null);
  const [exportAgentData, setExportAgentData] = useState<AgentType | undefined>(
    undefined,
  );
  const { permissions, userData } = useContext(AuthContext);
  const navigate = useCustomNavigate();
  const isAuth = true;
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const toggleControlPanelAgent = useToggleControlPanelAgent();
  const promoteMutation = usePostControlPanelPromote();
  const updateSharingMutation = usePutControlPanelAgentSharing();
  const validatePublishEmail = useValidatePublishEmail();
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canViewScheduler = can("view_control_panel");
  const canDirectPromoteToProd = can("prod_publish_approval_not_required");
  const requiresProdApproval = !canDirectPromoteToProd;
  const isSuperAdmin = userData?.role === "super_admin";

  const { data: promoteDepartments = [] } = useGetPublishDepartments(
    { agent_id: selectedPromoteAgentId },
    { enabled: isSuperAdmin && Boolean(selectedPromoteAgentId) },
  );

  const handleRowDoubleClick = (workflow: WorkagentType) => {
    const agentId = workflow.agentId;
    if (!agentId) return;
    const isCreator =
      userData?.email && workflow.userEmail && userData.email === workflow.userEmail;
    if (isCreator) {
      navigate(`/agent/${agentId}`);
    } else {
      navigate(`/agent/${agentId}/view`);
    }
  };

  const { data, isLoading } = useGetControlPanelAgents(
    {
      env: activeTab.toLowerCase() as "uat" | "prod",
      search: searchQuery || undefined,
      page: 1,
      size: 100,
    },
    {
      refetchInterval: 30000,
    },
  );

  // Pull active triggers so the Schedule column can flag agents that already
  // have automation configured — without this, users have to click into the
  // Scheduler dialog one agent at a time to find out.
  const { data: allTriggers = [] } = useGetAllTriggers(
    {},
    { enabled: canViewScheduler, refetchInterval: 30_000 },
  );
  // Triggers can be scoped to a specific deployment (deployment_id set) or to
  // an agent generally (deployment_id null — applies across UAT/PROD). We
  // bucket them separately so a UAT-only schedule doesn't mark the agent's
  // PROD row as scheduled.
  const { scheduledDeploymentIds, scheduledAgentIds } = useMemo(() => {
    const deps = new Set<string>();
    const agents = new Set<string>();
    for (const trig of allTriggers) {
      if (!trig.is_active) continue;
      if (trig.deployment_id) {
        deps.add(trig.deployment_id);
      } else if (trig.agent_id) {
        agents.add(trig.agent_id);
      }
    }
    return { scheduledDeploymentIds: deps, scheduledAgentIds: agents };
  }, [allTriggers]);
  const isWorkagentScheduled = (workflow: WorkagentType): boolean => {
    if (scheduledDeploymentIds.has(workflow.id)) return true;
    if (workflow.agentId && scheduledAgentIds.has(workflow.agentId)) return true;
    return false;
  };
  const displayworkflows = useMemo(() => {
    if (workflows?.length) {
      return workflows;
    }

    return (data?.items ?? []).map((item) => ({
        id: item.deploy_id,
        agentId: item.agent_id,
        name: item.agent_name,
        description: item.publish_description ?? item.agent_description ?? "",
        version: item.version_label ?? item.version_number ?? "-",
        runVersion: item.version_number
          ? String(item.version_number).startsWith("v")
            ? String(item.version_number)
            : `v${item.version_number}`
          : "",
        environment: activeTab.toLowerCase() as "uat" | "prod",
        visibility: item.visibility ?? "-",
        user: item.creator_name ?? "-",
        userEmail: item.creator_email ?? undefined,
        owner: item.owner_name ?? "-",
        ownerCount: item.owner_count ?? 0,
        ownerNames: item.owner_names ?? [],
        ownerEmails: item.owner_emails ?? [],
        department: item.creator_department ?? "Org-wide",
        createdAtRaw: item.created_at ?? undefined,
        created: formatDateTime(item.created_at),
        movedToProd: item.moved_to_prod ?? false,
        pendingProdApproval: item.pending_prod_approval ?? false,
        status: item.is_active,
        enabled: item.is_enabled,
        inputType: item.input_type,
      }));
  }, [workflows, data?.items, activeTab]);

  const creatorOptions = useMemo(() => {
    const names = new Set<string>();
    displayworkflows.forEach((workflow) => {
      if (workflow.user && workflow.user !== "-") names.add(workflow.user);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [displayworkflows]);

  const ownerOptions = useMemo(() => {
    const names = new Set<string>();
    displayworkflows.forEach((workflow) => {
      if (workflow.owner && workflow.owner !== "-") names.add(workflow.owner);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [displayworkflows]);

  const departmentOptions = useMemo(() => {
    const names = new Set<string>();
    displayworkflows.forEach((workflow) => {
      if (workflow.department && workflow.department !== "-") names.add(workflow.department);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [displayworkflows]);

  const versionOptions = useMemo(() => {
    const names = new Set<string>();
    displayworkflows.forEach((workflow) => {
      if (workflow.version && workflow.version !== "-") names.add(workflow.version);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [displayworkflows]);

  const getEffectiveEnabledState = (workflow: WorkagentType) =>
    workflowStates[workflow.id]?.enabled ?? workflow.enabled;

  const getEffectiveStartStopState = (workflow: WorkagentType) =>
    workflowStates[workflow.id]?.status ?? workflow.status;

  const matchesCreatedDateFilter = (
    createdValue: string,
    dateFilter: CreatedDateFilter,
  ) => {
    if (dateFilter === "all") return true;
    const createdDate = new Date(createdValue);
    if (Number.isNaN(createdDate.getTime())) return false;
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (dateFilter === "today") {
      return createdDate >= startOfToday;
    }
    const daysByFilter: Record<Exclude<CreatedDateFilter, "all" | "today">, number> = {
      "7d": 7,
      "30d": 30,
      "90d": 90,
    };
    const threshold = new Date(now);
    threshold.setDate(threshold.getDate() - daysByFilter[dateFilter]);
    return createdDate >= threshold;
  };

  const clearFilters = () => {
    setSelectedCreator("all");
    setSelectedOwner("all");
    setSelectedDepartment("all");
    setSelectedVersion("all");
    setSelectedEnabledState("all");
    setSelectedStartStopState("all");
    setSelectedCreatedDate("all");
  };

  const activeFilterCount = [
    selectedCreator,
    selectedOwner,
    selectedDepartment,
    selectedVersion,
    selectedEnabledState,
    selectedStartStopState,
    selectedCreatedDate,
  ].filter((value) => value !== "all").length;

  const activeFilterChips = [
    selectedCreator !== "all"
      ? {
          key: "creator",
          label: `creator: ${selectedCreator === "__none__" ? "unknown" : selectedCreator}`,
          onRemove: () => setSelectedCreator("all"),
        }
      : null,
    selectedOwner !== "all"
      ? {
          key: "owner",
          label: `owner: ${selectedOwner === "__none__" ? "unknown" : selectedOwner}`,
          onRemove: () => setSelectedOwner("all"),
        }
      : null,
    selectedDepartment !== "all"
      ? {
          key: "department",
          label: `department: ${selectedDepartment === "__none__" ? "none" : selectedDepartment}`,
          onRemove: () => setSelectedDepartment("all"),
        }
      : null,
    selectedVersion !== "all"
      ? {
          key: "version",
          label: `version: ${selectedVersion}`,
          onRemove: () => setSelectedVersion("all"),
        }
      : null,
    selectedEnabledState !== "all"
      ? {
          key: "enabled",
          label: `enabled: ${selectedEnabledState}`,
          onRemove: () => setSelectedEnabledState("all"),
        }
      : null,
    selectedStartStopState !== "all"
      ? {
          key: "status",
          label: `start/stop: ${selectedStartStopState}`,
          onRemove: () => setSelectedStartStopState("all"),
        }
      : null,
    selectedCreatedDate !== "all"
      ? {
          key: "created",
          label: `created: ${selectedCreatedDate === "today" ? "today" : `last ${selectedCreatedDate.replace("d", " days")}`}`,
          onRemove: () => setSelectedCreatedDate("all"),
        }
      : null,
  ].filter(
    (
      item,
    ): item is { key: string; label: string; onRemove: () => void } => Boolean(item),
  );

  const normalizedPromoteEmails = useMemo(
    () =>
      Array.from(
        new Set(
          promoteSelectedEmails
            .map((email) => email.trim().toLowerCase())
            .filter(Boolean),
        ),
      ),
    [promoteSelectedEmails],
  );

  const invalidPromoteEmails = useMemo(() => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return normalizedPromoteEmails.filter((email) => !emailRegex.test(email));
  }, [normalizedPromoteEmails]);

  const { data: promoteSharingData, isLoading: isPromoteSharingLoading } =
    useGetControlPanelAgentSharing(
      { deploy_id: selectedPromoteDeployId },
      {
        enabled:
          promoteDialogOpen &&
          selectedPromoteVisibility === "PRIVATE" &&
          Boolean(selectedPromoteDeployId),
      },
    );

  const { data: sharingData, isLoading: isSharingLoading } =
    useGetControlPanelAgentSharing(
      { deploy_id: selectedSharingDeployId },
      {
        enabled: sharingDialogOpen && Boolean(selectedSharingDeployId),
      },
    );

  const {
    data: rawPromoteEmailSuggestions = [],
    isFetching: isFetchingPromoteEmailSuggestions,
  } = useGetPublishEmailSuggestions(
    {
      agent_id: selectedPromoteAgentId,
      q: debouncedPromoteEmailQuery,
      limit: 8,
    },
    {
      enabled:
        promoteDialogOpen &&
        selectedPromoteVisibility === "PRIVATE" &&
        !!selectedPromoteAgentId &&
        debouncedPromoteEmailQuery.trim().length > 0,
    },
  );

  const {
    data: rawSharingEmailSuggestions = [],
    isFetching: isFetchingSharingEmailSuggestions,
  } = useGetPublishEmailSuggestions(
    {
      agent_id: selectedSharingAgentId,
      q: debouncedSharingEmailQuery,
      limit: 8,
    },
    {
      enabled:
        sharingDialogOpen &&
        !!selectedSharingAgentId &&
        debouncedSharingEmailQuery.trim().length > 0,
    },
  );

  const promoteEmailSuggestions = useMemo(
    () =>
      rawPromoteEmailSuggestions.filter(
        (item) =>
          !normalizedPromoteEmails.includes(item.email.trim().toLowerCase()),
      ),
    [rawPromoteEmailSuggestions, normalizedPromoteEmails],
  );

  const normalizedSharingEmails = useMemo(
    () =>
      Array.from(
        new Set(
          sharingSelectedEmails
            .map((email) => email.trim().toLowerCase())
            .filter(Boolean),
        ),
      ),
    [sharingSelectedEmails],
  );

  const invalidSharingEmails = useMemo(() => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return normalizedSharingEmails.filter((email) => !emailRegex.test(email));
  }, [normalizedSharingEmails]);

  const sharingEmailSuggestions = useMemo(
    () =>
      rawSharingEmailSuggestions.filter(
        (item) =>
          !normalizedSharingEmails.includes(item.email.trim().toLowerCase()),
      ),
    [rawSharingEmailSuggestions, normalizedSharingEmails],
  );

  useEffect(() => {
    const initialStates: {
      [key: string]: { status: boolean; enabled: boolean };
    } = {};
    displayworkflows.forEach((workflow) => {
      initialStates[workflow.id] = {
        status: workflow.status,
        enabled: workflow.enabled,
      };
    });
    setWorkagentStates(initialStates);
  }, [displayworkflows]);

  useEffect(() => {
    if (!promoteDialogOpen) {
      setDebouncedPromoteEmailQuery("");
      return;
    }
    const timer = setTimeout(() => {
      setDebouncedPromoteEmailQuery(promoteEmailDraft.trim().toLowerCase());
    }, 220);
    return () => clearTimeout(timer);
  }, [promoteEmailDraft, promoteDialogOpen]);

  useEffect(() => {
    if (!sharingDialogOpen) {
      setDebouncedSharingEmailQuery("");
      return;
    }
    const timer = setTimeout(() => {
      setDebouncedSharingEmailQuery(sharingEmailDraft.trim().toLowerCase());
    }, 220);
    return () => clearTimeout(timer);
  }, [sharingEmailDraft, sharingDialogOpen]);

  useEffect(() => {
    if (
      !promoteDialogOpen ||
      selectedPromoteVisibility !== "PRIVATE" ||
      promoteRecipientsInitialized
    ) {
      return;
    }
    if (isPromoteSharingLoading) {
      return;
    }
    setPromoteSelectedEmails(promoteSharingData?.recipient_emails ?? []);
    setPromoteRecipientsInitialized(true);
  }, [
    promoteDialogOpen,
    selectedPromoteVisibility,
    promoteRecipientsInitialized,
    isPromoteSharingLoading,
    promoteSharingData?.recipient_emails,
  ]);

  useEffect(() => {
    if (!sharingDialogOpen || sharingRecipientsInitialized) {
      return;
    }
    if (isSharingLoading) {
      return;
    }
    setSharingSelectedEmails(sharingData?.recipient_emails ?? []);
    setSharingRecipientsInitialized(true);
  }, [
    sharingDialogOpen,
    sharingRecipientsInitialized,
    isSharingLoading,
    sharingData?.recipient_emails,
  ]);

  const handleStatusToggle = async (workflowId: string) => {
    const currentStatus = workflowStates[workflowId]?.status ?? false;
    const nextStatus = !currentStatus;
    const env = activeTab.toLowerCase() as "uat" | "prod";

    setWorkagentStates((prev) => ({
      ...prev,
      [workflowId]: {
        ...prev[workflowId],
        status: nextStatus,
      },
    }));
    setPendingToggles((prev) => ({
      ...prev,
      [workflowId]: {
        ...(prev[workflowId] ?? { status: false, enabled: false }),
        status: true,
      },
    }));

    try {
      await toggleControlPanelAgent.mutateAsync({
        deployId: workflowId,
        env,
        field: "is_active",
        value: nextStatus,
      });
    } catch (error: any) {
      setWorkagentStates((prev) => ({
        ...prev,
        [workflowId]: {
          ...prev[workflowId],
          status: currentStatus,
        },
      }));
      setErrorData({
        title: t("Failed to update Start/Stop state"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setPendingToggles((prev) => ({
        ...prev,
        [workflowId]: {
          ...(prev[workflowId] ?? { status: false, enabled: false }),
          status: false,
        },
      }));
    }
  };

  const handleEnabledToggle = async (workflowId: string) => {
    const currentEnabled = workflowStates[workflowId]?.enabled ?? false;
    const nextEnabled = !currentEnabled;
    const env = activeTab.toLowerCase() as "uat" | "prod";

    setWorkagentStates((prev) => ({
      ...prev,
      [workflowId]: {
        ...prev[workflowId],
        enabled: nextEnabled,
      },
    }));
    setPendingToggles((prev) => ({
      ...prev,
      [workflowId]: {
        ...(prev[workflowId] ?? { status: false, enabled: false }),
        enabled: true,
      },
    }));

    try {
      await toggleControlPanelAgent.mutateAsync({
        deployId: workflowId,
        env,
        field: "is_enabled",
        value: nextEnabled,
      });
    } catch (error: any) {
      setWorkagentStates((prev) => ({
        ...prev,
        [workflowId]: {
          ...prev[workflowId],
          enabled: currentEnabled,
        },
      }));
      setErrorData({
        title: t("Failed to update Enable/Disable state"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setPendingToggles((prev) => ({
        ...prev,
        [workflowId]: {
          ...(prev[workflowId] ?? { status: false, enabled: false }),
          enabled: false,
        },
      }));
    }
  };

  const setSharingContext = (workflow: WorkagentType) => {
    setSelectedSharingAgentId(workflow.agentId ?? "");
    setSelectedSharingAgentName(workflow.name ?? "");
    setSelectedSharingEnvironment(
      workflow.environment ?? (activeTab.toLowerCase() as "uat" | "prod"),
    );
    setSelectedSharingVersion(workflow.runVersion ?? "");
  };

  const handleOpenWidgetExport = (workflow: WorkagentType) => {
    setSharingContext(workflow);
    setOpenEmbedModal(true);
  };

  const handleOpenSharingDialog = (workflow: WorkagentType) => {
    setSelectedSharingDeployId(workflow.id);
    setSelectedSharingAgentId(workflow.agentId ?? "");
    setSelectedSharingAgentName(workflow.name ?? "");
    setSharingSelectedEmails([]);
    setSharingEmailDraft("");
    setSharingRecipientsInitialized(false);
    setSharingDialogOpen(true);
  };

  const handleOpenExportJson = async (workflow: WorkagentType) => {
    const agentId = workflow.agentId ?? "";
    if (!agentId) {
      setErrorData({
        title: t("Agent not found"),
        list: [t("Unable to load agent data for export.")],
      });
      return;
    }

    try {
      setSharingContext(workflow);
      if (!exportAgentData || exportAgentData.id !== agentId) {
        const response = await api.get(
          `${getURL("PUBLISH")}/${workflow.id}/snapshot`,
        );
        const snapshotPayload = response?.data ?? {};
        const snapshotData = snapshotPayload?.agent_snapshot ?? null;

        const agentForExport: AgentType = {
          id: String(snapshotPayload?.agent_id ?? agentId),
          name: String(snapshotPayload?.agent_name ?? workflow.name ?? "agent"),
          description: String(
            snapshotPayload?.agent_description ?? workflow.description ?? "",
          ),
          data: snapshotData,
          endpoint_name: null,
          tags: [],
          is_component: false,
        };
        setExportAgentData(agentForExport);
      }
      setOpenExportModal(true);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to load agent for export"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    }
  };

  const handlePromoteToProd = async () => {
    if (!selectedPromoteDeployId) return;
    setPromotingById((prev) => ({ ...prev, [selectedPromoteDeployId]: true }));

    if (
      selectedPromoteVisibility === "PRIVATE" &&
      invalidPromoteEmails.length > 0
    ) {
      setErrorData({
        title: t("Invalid email format"),
        list: invalidPromoteEmails,
      });
      setPromotingById((prev) => ({
        ...prev,
        [selectedPromoteDeployId]: false,
      }));
      return;
    }

    if (
      selectedPromoteVisibility === "PRIVATE" &&
      selectedPromoteAgentId &&
      normalizedPromoteEmails.length > 0
    ) {
      try {
        const validationResults = await Promise.all(
          normalizedPromoteEmails.map((email) =>
            validatePublishEmail.mutateAsync({
              agent_id: selectedPromoteAgentId,
              email,
            }),
          ),
        );
        const invalidUsers = validationResults
          .filter((result) => !result.exists_in_department)
          .map((result) => result.email);
        if (invalidUsers.length > 0) {
          setErrorData({
            title: t("Some users are not available in this department."),
            list: invalidUsers,
          });
          setPromotingById((prev) => ({
            ...prev,
            [selectedPromoteDeployId]: false,
          }));
          return;
        }
      } catch (error: any) {
        setErrorData({
          title: t("Email validation failed"),
          list: [
            error?.response?.data?.detail ||
              error?.message ||
              t("Unknown error"),
          ],
        });
        setPromotingById((prev) => ({
          ...prev,
          [selectedPromoteDeployId]: false,
        }));
        return;
      }
    }

    try {
      const response = await promoteMutation.mutateAsync({
        deploy_id: selectedPromoteDeployId,
        visibility: selectedPromoteVisibility,
        recipient_emails:
          selectedPromoteVisibility === "PRIVATE"
            ? normalizedPromoteEmails
            : undefined,
        ...(isSuperAdmin && selectedPromoteDepartmentId
          ? { department_id: selectedPromoteDepartmentId }
          : {}),
      });
      setSuccessData({
        title: response?.message || t("Promotion request submitted."),
        link: "/workflows",
      });
      setPromoteDialogOpen(false);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to move UAT deployment to PROD"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setPromotingById((prev) => ({
        ...prev,
        [selectedPromoteDeployId]: false,
      }));
    }
  };

  const handleOpenPromoteDialog = (workflowId: string) => {
    setSelectedPromoteDeployId(workflowId);
    const workflow = displayworkflows.find((item) => item.id === workflowId);
    setSelectedPromoteAgentId(workflow?.agentId ?? "");
    setSelectedPromoteVisibility("PRIVATE");
    setSelectedPromoteDepartmentId("");
    setPromoteSelectedEmails([]);
    setPromoteEmailDraft("");
    setPromoteRecipientsInitialized(false);
    setPromoteDialogOpen(true);
  };

  const addSharingEmails = (rawValue: string) => {
    const parsed = rawValue
      .split(/[\n,;\s]+/)
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean);
    if (parsed.length === 0) return;

    setSharingSelectedEmails((prev) => {
      const merged = new Set(prev.map((email) => email.trim().toLowerCase()));
      parsed.forEach((email) => merged.add(email));
      return Array.from(merged);
    });
  };

  const removeSharingEmail = (email: string) => {
    const normalized = email.trim().toLowerCase();
    setSharingSelectedEmails((prev) =>
      prev.filter((item) => item.trim().toLowerCase() !== normalized),
    );
  };

  const handleSaveSharing = async () => {
    if (!selectedSharingDeployId) return;

    if (invalidSharingEmails.length > 0) {
      setErrorData({
        title: t("Invalid email format"),
        list: invalidSharingEmails,
      });
      return;
    }

    if (selectedSharingAgentId && normalizedSharingEmails.length > 0) {
      try {
        const validationResults = await Promise.all(
          normalizedSharingEmails.map((email) =>
            validatePublishEmail.mutateAsync({
              agent_id: selectedSharingAgentId,
              email,
            }),
          ),
        );
        const invalidUsers = validationResults
          .filter((result) => !result.exists_in_department)
          .map((result) => result.email);
        if (invalidUsers.length > 0) {
          setErrorData({
            title: t("Some users are not available in this department."),
            list: invalidUsers,
          });
          return;
        }
      } catch (error: any) {
        setErrorData({
          title: t("Email validation failed"),
          list: [
            error?.response?.data?.detail ||
              error?.message ||
              t("Unknown error"),
          ],
        });
        return;
      }
    }

    try {
      setSavingSharing(true);
      await updateSharingMutation.mutateAsync({
        deploy_id: selectedSharingDeployId,
        recipient_emails: normalizedSharingEmails,
      });
      setSuccessData({
        title: t("Sharing options updated successfully."),
      });
      setSharingDialogOpen(false);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to update sharing options"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setSavingSharing(false);
    }
  };

  const addPromoteEmails = (rawValue: string) => {
    const parsed = rawValue
      .split(/[\n,;\s]+/)
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean);
    if (parsed.length === 0) return;

    setPromoteSelectedEmails((prev) => {
      const merged = new Set(prev.map((email) => email.trim().toLowerCase()));
      parsed.forEach((email) => merged.add(email));
      return Array.from(merged);
    });
  };

  const removePromoteEmail = (email: string) => {
    const normalized = email.trim().toLowerCase();
    setPromoteSelectedEmails((prev) =>
      prev.filter((item) => item.trim().toLowerCase() !== normalized),
    );
  };

  const filteredworkflows = displayworkflows.filter((workflow) => {
    const matchesSearch =
      !searchQuery ||
      workflow.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.user.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (workflow.owner ?? "")
        .toLowerCase()
        .includes(searchQuery.toLowerCase()) ||
      workflow.department.toLowerCase().includes(searchQuery.toLowerCase());

    const creatorLabel = workflow.user || "";
    const ownerLabel = workflow.owner || "";
    const departmentLabel = workflow.department || "";
    const versionLabel = workflow.version || "";
    const isEnabled = getEffectiveEnabledState(workflow);
    const isRunning = getEffectiveStartStopState(workflow);

    const matchesCreator =
      selectedCreator === "all" ||
      (selectedCreator === "__none__" && (!creatorLabel || creatorLabel === "-")) ||
      creatorLabel === selectedCreator;

    const matchesOwner =
      selectedOwner === "all" ||
      (selectedOwner === "__none__" && (!ownerLabel || ownerLabel === "-")) ||
      ownerLabel === selectedOwner;

    const matchesDepartment =
      selectedDepartment === "all" ||
      (selectedDepartment === "__none__" && (!departmentLabel || departmentLabel === "-")) ||
      departmentLabel === selectedDepartment;

    const matchesVersion =
      selectedVersion === "all" ||
      versionLabel === selectedVersion;

    const matchesEnabled =
      selectedEnabledState === "all" ||
      (selectedEnabledState === "enabled" && isEnabled) ||
      (selectedEnabledState === "disabled" && !isEnabled);

    const matchesStartStop =
      selectedStartStopState === "all" ||
      (selectedStartStopState === "running" && isRunning) ||
      (selectedStartStopState === "stopped" && !isRunning);

    const matchesCreatedDate = matchesCreatedDateFilter(
      workflow.createdAtRaw || workflow.created,
      selectedCreatedDate,
    );

    return (
      matchesSearch &&
      matchesCreator &&
      matchesOwner &&
      matchesDepartment &&
      matchesVersion &&
      matchesEnabled &&
      matchesStartStop &&
      matchesCreatedDate
    );
  });

  useEffect(() => {
    if (!setSearch) return;
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  const tableColumnCount =
    6 +
    (activeTab === "PROD" ? 1 : 0) +
    (can("share_agent") ? 1 : 0) +
    (can("move_uat_to_prod") && activeTab === "UAT" ? 1 : 0) +
    (canViewScheduler ? 1 : 0) +
    (can("start_stop_agent") ? 1 : 0) +
    (can("enable_disable_agent") ? 1 : 0);

  const tableScrollRef = useRef<HTMLDivElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const phantomRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);

  useEffect(() => {
    const scroll = tableScrollRef.current;
    const mirror = mirrorRef.current;
    const phantom = phantomRef.current;
    if (!scroll || !mirror || !phantom) return;
    const syncWidth = () => { phantom.style.width = `${scroll.scrollWidth}px`; };
    syncWidth();
    const ro = new ResizeObserver(syncWidth);
    ro.observe(scroll);
    // Also watch inner content so phantom re-syncs when the table widens
    // after async data loads (ResizeObserver only fires on observed-element
    // size changes, not on scrollWidth growth of its children).
    const inner = scroll.firstElementChild as Element | null;
    if (inner) ro.observe(inner);
    const raf = requestAnimationFrame(syncWidth);
    const onScrollContent = () => {
      if (syncingRef.current) return;
      syncingRef.current = true;
      mirror.scrollLeft = scroll.scrollLeft;
      syncingRef.current = false;
    };
    const onScrollMirror = () => {
      if (syncingRef.current) return;
      syncingRef.current = true;
      scroll.scrollLeft = mirror.scrollLeft;
      syncingRef.current = false;
    };
    scroll.addEventListener("scroll", onScrollContent, { passive: true });
    mirror.addEventListener("scroll", onScrollMirror, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      scroll.removeEventListener("scroll", onScrollContent);
      mirror.removeEventListener("scroll", onScrollMirror);
    };
  }, []);

  return (
      <div className="flex h-full w-full flex-col overflow-hidden">
        <div className="flex-shrink-0 border-b px-4 py-3 sm:px-6 md:px-8 md:py-4">
          <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("Agent Control Panel")}</h1>
            <div className="inline-flex rounded-lg border border-border bg-muted/30 p-1">
              <button
                type="button"
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                  activeTab === "UAT"
                    ? "bg-[var(--button-primary)] text-[var(--button-primary-foreground)] shadow-sm"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
                onClick={() => setActiveTab("UAT")}
              >
                UAT
              </button>
              <button
                type="button"
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                  activeTab === "PROD"
                    ? "bg-[var(--button-primary)] text-[var(--button-primary-foreground)] shadow-sm"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
                onClick={() => setActiveTab("PROD")}
              >
                PROD
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder={t("Search agents...")}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-64 rounded-lg border bg-card py-2 pl-10 pr-4 text-sm"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              className="gap-2"
              onClick={() => setShowFilters(true)}
            >
              <Filter className="h-4 w-4" />
              Filters
              {activeFilterCount > 0 && (
                <span className="rounded-full bg-primary px-1.5 py-0.5 text-xs text-primary-foreground">
                  {activeFilterCount}
                </span>
              )}
            </Button>
          </div>
        </div>
      </div>

      {activeFilterChips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b bg-muted/20 px-4 py-3 sm:px-6 md:px-8">
          {activeFilterChips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={chip.onRemove}
              className="inline-flex items-center gap-1 rounded-full border bg-background px-3 py-1 text-xs text-foreground hover:bg-muted"
            >
              <span>{chip.label}</span>
              <X className="h-3 w-3" />
            </button>
          ))}
          <button
            type="button"
            onClick={clearFilters}
            className="text-xs text-primary hover:underline"
          >
            Clear all
          </button>
        </div>
      )}

      {showFilters && (
        <>
          <div
            className="fixed inset-0 z-[60] bg-black/40 transition-opacity"
            onClick={() => setShowFilters(false)}
          />
          <div className="fixed inset-x-0 top-0 z-[70] flex h-full w-full items-start justify-center p-4">
            <div className="flex h-full max-h-[720px] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border bg-background shadow-xl transition-transform">
              <div className="flex items-center justify-between border-b px-5 py-4">
                <h2 className="text-lg font-semibold">Filters</h2>
                <div className="flex items-center gap-3">
                  <button
                    onClick={clearFilters}
                    className="text-sm text-primary hover:underline"
                  >
                    Clear Filters
                  </button>
                  <button
                    onClick={() => setShowFilters(false)}
                    className="rounded-md p-1 text-muted-foreground hover:text-foreground"
                    aria-label="Close filters"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>

              <div className="flex flex-1 overflow-hidden">
                <div className="w-44 border-r bg-muted/40 p-3 text-sm">
                  <div className="space-y-4">
                    <div>
                      <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        People
                      </div>
                      <div className="flex flex-col gap-1">
                        <button
                          onClick={() => setActiveFilterTab("creator")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "creator"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          Creator
                        </button>
                        <button
                          onClick={() => setActiveFilterTab("owner")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "owner"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          Owner
                        </button>
                        <button
                          onClick={() => setActiveFilterTab("department")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "department"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          Department
                        </button>
                      </div>
                    </div>

                    <div>
                      <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Deployment
                      </div>
                      <div className="flex flex-col gap-1">
                        <button
                          onClick={() => setActiveFilterTab("version")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "version"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          Version
                        </button>
                        <button
                          onClick={() => setActiveFilterTab("deployment")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "deployment"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          States
                        </button>
                      </div>
                    </div>

                    <div>
                      <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Timeline
                      </div>
                      <div className="flex flex-col gap-1">
                        <button
                          onClick={() => setActiveFilterTab("timeline")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "timeline"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          Created Date
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex-1 overflow-auto p-5">
                  {activeFilterTab === "creator" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">Creator</h3>
                      <select
                        value={selectedCreator}
                        onChange={(e) => setSelectedCreator(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">All creators</option>
                        <option value="__none__">Unknown creator</option>
                        {creatorOptions.map((creator) => (
                          <option key={creator} value={creator}>
                            {creator}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "owner" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">Owner</h3>
                      <select
                        value={selectedOwner}
                        onChange={(e) => setSelectedOwner(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">All owners</option>
                        <option value="__none__">Unknown owner</option>
                        {ownerOptions.map((owner) => (
                          <option key={owner} value={owner}>
                            {owner}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "department" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">Department</h3>
                      <select
                        value={selectedDepartment}
                        onChange={(e) => setSelectedDepartment(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">All departments</option>
                        <option value="__none__">No department</option>
                        {departmentOptions.map((department) => (
                          <option key={department} value={department}>
                            {department}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "version" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">Version</h3>
                      <select
                        value={selectedVersion}
                        onChange={(e) => setSelectedVersion(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">All versions</option>
                        {versionOptions.map((version) => (
                          <option key={version} value={version}>
                            {version}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "deployment" && (
                    <div className="space-y-6">
                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Enabled State</h3>
                        <select
                          value={selectedEnabledState}
                          onChange={(e) => setSelectedEnabledState(e.target.value)}
                          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                        >
                          <option value="all">All</option>
                          <option value="enabled">Enabled</option>
                          <option value="disabled">Disabled</option>
                        </select>
                      </div>
                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Start/Stop State</h3>
                        <select
                          value={selectedStartStopState}
                          onChange={(e) => setSelectedStartStopState(e.target.value)}
                          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                        >
                          <option value="all">All</option>
                          <option value="running">Running</option>
                          <option value="stopped">Stopped</option>
                        </select>
                      </div>
                    </div>
                  )}

                  {activeFilterTab === "timeline" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">Created Date</h3>
                      <select
                        value={selectedCreatedDate}
                        onChange={(e) =>
                          setSelectedCreatedDate(e.target.value as CreatedDateFilter)
                        }
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">Any time</option>
                        <option value="today">Today</option>
                        <option value="7d">Last 7 days</option>
                        <option value="30d">Last 30 days</option>
                        <option value="90d">Last 90 days</option>
                      </select>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      <style>{`
        .wf-table-scroll::-webkit-scrollbar { height: 0; }
        .wf-table-scroll { scrollbar-width: none; }
        .wf-mirror-bar::-webkit-scrollbar { height: 8px; }
        .wf-mirror-bar::-webkit-scrollbar-track { background: hsl(var(--muted)); border-radius: 9999px; }
        .wf-mirror-bar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground)); border-radius: 9999px; }
        .wf-mirror-bar::-webkit-scrollbar-thumb:hover { background: hsl(var(--foreground) / 0.8); }
        .wf-mirror-bar { scrollbar-width: thin; scrollbar-color: hsl(var(--muted-foreground)) hsl(var(--muted)); }
      `}</style>
      <div className="flex-1 flex flex-col overflow-hidden p-4 sm:p-6 gap-3">
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border bg-card">
          <div ref={tableScrollRef} className="wf-table-scroll flex-1 overflow-auto">
            <table style={{ width: "max-content", minWidth: "100%" }} className="table-fixed text-sm">
            <colgroup>
              <col className="w-[20rem]" />
              <col className="w-[6.5rem]" />
              <col className="w-[8.5rem]" />
              <col className="w-[9rem]" />
              <col className="w-[8.5rem]" />
              {activeTab === "PROD" && <col className="w-[7rem]" />}
              <col className="w-[11rem]" />
              {can("share_agent") && <col className="w-[8rem]" />}
              {can("move_uat_to_prod") && activeTab === "UAT" && <col className="w-[8rem]" />}
              {canViewScheduler && <col className="w-[7rem]" />}
              {can("start_stop_agent") && <col className="w-[6rem]" />}
              {can("enable_disable_agent") && <col className="w-[7rem]" />}
            </colgroup>
            <thead className="sticky top-0 z-10 border-b bg-card">
              <tr>
                <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("Agent Name")}
                </th>
                <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("Version")}
                </th>
                <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("Creator")}
                </th>
                <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <ShadTooltip content={t("Business Owner")}>
                    <span className="cursor-help">{t("Business Owner")}</span>
                  </ShadTooltip>
                </th>
                <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("Department")}
                </th>
                {activeTab === "PROD" && (
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Visibility")}
                  </th>
                )}
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Created At")}
                  </th>
                {can("share_agent") && (
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Sharing Options")}
                  </th>
                )}
                {can("move_uat_to_prod") && activeTab === "UAT" && (
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Move UAT to PROD")}
                  </th>
                )}
                {canViewScheduler && (
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Agent Scheduler")}
                  </th>
                )}
                {can("start_stop_agent") && (
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Start/Stop")}
                  </th>
                )}
                {can("enable_disable_agent") && (
                  <th className="bg-muted/30 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Enable/Disable")}
                  </th>
                )}
              </tr>
            </thead>

            <tbody className="divide-y">
              {isLoading ? (
                <tr>
                  <td colSpan={tableColumnCount} className="px-6 py-10 text-center">
                    <div className="flex items-center justify-center">
                      <CustomLoader />
                    </div>
                  </td>
                </tr>
              ) : filteredworkflows.length === 0 ? (
                <tr>
                  <td
                    colSpan={tableColumnCount}
                    className="px-6 py-10 text-center text-sm text-muted-foreground"
                  >
                    {t("No deployed agents found")}
                  </td>
                </tr>
              ) : (
                filteredworkflows.map((workflow) => (
                  <tr
                    key={workflow.id}
                    className="cursor-pointer align-top transition-colors hover:bg-muted/30"
                    onClick={() => onWorkagentClick?.(workflow)}
                    onDoubleClick={() => handleRowDoubleClick(workflow)}
                  >
                  <td className="px-4 py-3">
                      <div className="truncate font-semibold" title={workflow.name}>
                        {workflow.name}
                      </div>
                      <div
                        className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground"
                        title={workflow.description || ""}
                      >
                        {workflow.description?.trim() || ""}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm font-medium whitespace-nowrap">
                      {workflow.version ?? "-"}
                    </td>

                    <td className="px-4 py-3 text-sm">
                      {workflow.userEmail ? (
                        <ShadTooltip content={workflow.userEmail}>
                          <span className="block truncate cursor-help" title={workflow.user}>
                            {workflow.user}
                          </span>
                        </ShadTooltip>
                      ) : (
                        <span className="block truncate" title={workflow.user}>
                          {workflow.user}
                        </span>
                      )}
                    </td>

                    <td className="px-4 py-3 text-sm">
                      <div className="flex items-center gap-1.5">
                        {(workflow.ownerEmails?.length ?? 0) > 0 ? (
                          <ShadTooltip
                            content={(workflow.ownerEmails ?? []).join(", ")}
                          >
                            <span className="block truncate cursor-help" title={workflow.owner ?? "-"}>
                              {(workflow.ownerCount ?? 0) > 1
                                ? `${workflow.owner ?? "-"} +${(workflow.ownerCount ?? 0) - 1}`
                                : (workflow.owner ?? "-")}
                            </span>
                          </ShadTooltip>
                        ) : (
                          <span className="block truncate" title={workflow.owner ?? "-"}>
                            {(workflow.ownerCount ?? 0) > 1
                              ? `${workflow.owner ?? "-"} +${(workflow.ownerCount ?? 0) - 1}`
                              : (workflow.owner ?? "-")}
                          </span>
                        )}
                        {(workflow.ownerNames?.length ?? 0) > 1 && (
                          <ShadTooltip
                            content={(workflow.ownerEmails ?? []).join(", ")}
                          >
                            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-muted-foreground/30 text-muted-foreground">
                              <Info className="h-3 w-3" />
                            </span>
                          </ShadTooltip>
                        )}
                      </div>
                    </td>

                    <td className="px-4 py-3 text-sm">
                      <span className="block truncate" title={workflow.department}>
                        {workflow.department}
                      </span>
                    </td>

                    {activeTab === "PROD" && (
                      <td className="px-4 py-3 text-sm">
                        <span
                          className={`inline-flex rounded-full border px-2 py-1 text-xs font-medium ${
                            workflow.visibility === "PUBLIC"
                              ? "border-green-200 bg-green-50 text-green-700"
                              : "border-slate-200 bg-slate-50 text-slate-700"
                          }`}
                        >
                          {workflow.visibility ?? "-"}
                        </span>
                      </td>
                    )}

                    <td className="px-4 py-3 text-sm whitespace-nowrap text-muted-foreground">
                      {workflow.created}
                    </td>
                    {can("share_agent") && (
                      <td className="px-4 py-3 whitespace-nowrap">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs hover:bg-muted"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Share2 className="h-3.5 w-3.5" />
                              {t("Share")}
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent
                            align="start"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                handleOpenSharingDialog(workflow);
                              }}
                            >
                              {t("Edit shared users")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleOpenExportJson(workflow);
                              }}
                            >
                              {t("Export as JSON")}
                            </DropdownMenuItem>
                            <DropdownMenuItem 
                              onClick={(e) => {
                                e.stopPropagation();
                                handleOpenWidgetExport(workflow);
                              }}
                            >
                              {t("Export as Widget")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                setExportApiAgent({
                                  agentId: workflow.agentId ?? "",
                                  agentName: workflow.name,
                                  version: workflow.version ?? "v1",
                                  deployId: workflow.id,
                                });
                                setOpenExportApiModal(true);
                              }}
                            >
                              {t("Export as API")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </td>
                    )}
                    {can("move_uat_to_prod") && activeTab === "UAT" && (
                      <td className="px-4 py-3 whitespace-nowrap">
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                          disabled={
                            promotingById[workflow.id] ||
                            workflow.pendingProdApproval
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            if (workflow.pendingProdApproval) return;
                            handleOpenPromoteDialog(workflow.id);
                          }}
                        >
                          <ArrowUpToLine className="h-3.5 w-3.5" />
                          {workflow.pendingProdApproval
                            ? t("Pending")
                            : promotingById[workflow.id]
                            ? t("Moving...")
                            : t("Move")}
                        </button>
                      </td>
                    )}
                    {canViewScheduler && (
                      <td className="px-4 py-3 whitespace-nowrap">
                        {(() => {
                          const isChat = workflow.inputType === "chat";
                          const isEnabled =
                            workflowStates[workflow.id]?.enabled ?? workflow.enabled;
                          const isStarted =
                            workflowStates[workflow.id]?.status ?? workflow.status;
                          const isInactive = !isEnabled || !isStarted;
                          const disabledReason = isChat
                            ? "Chat agents cannot be scheduled."
                            : !isEnabled
                              ? "Disabled agents cannot be scheduled. Enable the agent first."
                              : !isStarted
                                ? "Stopped agents cannot be scheduled. Start the agent first."
                                : undefined;
                          const isDisabled = isChat || isInactive;
                          const isScheduled = !isDisabled && isWorkagentScheduled(workflow);
                          const button = (
                            <button
                              type="button"
                              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors ${
                                isDisabled
                                  ? "cursor-not-allowed border-muted-foreground/30 text-muted-foreground"
                                  : isScheduled
                                    ? "border-green-600 bg-green-50 font-medium text-green-700 hover:bg-green-100 dark:bg-green-950/30 dark:text-green-400 dark:hover:bg-green-950/50"
                                    : "hover:bg-muted"
                              }`}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (isDisabled) return;
                                setSchedulerAgent(workflow);
                              }}
                              aria-disabled={isDisabled}
                            >
                              {isScheduled ? t("Scheduled") : t("Schedule")}
                            </button>
                          );

                          if (disabledReason) {
                            return (
                              <ShadTooltip content={disabledReason}>
                                <span>{button}</span>
                              </ShadTooltip>
                            );
                          }

                          if (isScheduled) {
                            return (
                              <ShadTooltip content={t("This agent has an active schedule. Click to view or edit.")}>
                                <span>{button}</span>
                              </ShadTooltip>
                            );
                          }

                          return button;
                        })()}
                      </td>
                    )}
                    {can("start_stop_agent") && (
                      <td className="px-4 py-3 whitespace-nowrap">
                        {(() => {
                          const isEnabled =
                            workflowStates[workflow.id]?.enabled ?? workflow.enabled;
                          const isStopped = !isEnabled;
                          const disabled = pendingToggles[workflow.id]?.status || isStopped;
                          return (
                            <button
                              type="button"
                              disabled={disabled}
                              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                                isStopped
                                  ? "bg-muted"
                                  : (workflowStates[workflow.id]?.status ?? workflow.status)
                                    ? "bg-blue-600"
                                    : "bg-muted"
                              }`}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (pendingToggles[workflow.id]?.status) return;
                                const currentStatus =
                                  workflowStates[workflow.id]?.status ??
                                  workflow.status;
                                setToggleConfirm({
                                  workflowId: workflow.id,
                                  kind: "status",
                                  nextValue: !currentStatus,
                                  agentName: workflow.name ?? "",
                                });
                              }}
                            >
                              <span
                                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                  isStopped
                                    ? "translate-x-1"
                                    : (workflowStates[workflow.id]?.status ?? workflow.status)
                                    ? "translate-x-6"
                                    : "translate-x-1"
                                }`}
                              />
                            </button>
                          );
                        })()}
                      </td>
                    )}
                    {can("enable_disable_agent") && (
                      <td className="px-4 py-3 whitespace-nowrap">
                        <button
                          type="button"
                          disabled={pendingToggles[workflow.id]?.enabled}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                            workflowStates[workflow.id]?.enabled
                              ? "bg-green-500"
                              : "bg-muted"
                          }`}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (pendingToggles[workflow.id]?.enabled) return;
                            const currentEnabled =
                              workflowStates[workflow.id]?.enabled ??
                              workflow.enabled;
                            setToggleConfirm({
                              workflowId: workflow.id,
                              kind: "enabled",
                              nextValue: !currentEnabled,
                              agentName: workflow.name ?? "",
                            });
                          }}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                              workflowStates[workflow.id]?.enabled
                                ? "translate-x-6"
                                : "translate-x-1"
                            }`}
                          />
                        </button>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
          </div>
          <div ref={mirrorRef} className="wf-mirror-bar flex-shrink-0 overflow-x-scroll overflow-y-hidden border-t" style={{ height: 12 }}>
            <div ref={phantomRef} style={{ height: 1 }} />
          </div>
        </div>
        <div className="flex items-center justify-between flex-shrink-0">
          <div className="text-sm text-muted-foreground">
            {t("Rows per page")}
          </div>
          <div className="flex items-center gap-2">
            <button className="rounded-lg border bg-card px-4 py-2 text-sm hover:bg-muted">
              {t("Previous")}
            </button>
            <button className="rounded-lg border bg-card px-4 py-2 text-sm hover:bg-muted">
              {t("Next")}
            </button>
          </div>
        </div>
      </div>

      <Dialog
        open={Boolean(schedulerAgent)}
        onOpenChange={(open) => {
          if (!open) setSchedulerAgent(null);
        }}
      >
        <DialogContent className="max-w-5xl p-0">
          {schedulerAgent && (
            <SchedulerPage
              embedded
              agentFilter={{
                deploymentId: schedulerAgent.id,
                agentId: schedulerAgent.agentId,
                agentName: schedulerAgent.name,
              }}
              lockedEnvironment={activeTab.toLowerCase() as "uat" | "prod"}
              onRequestClose={() => setSchedulerAgent(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      <ExportModal
        open={openExportModal}
        setOpen={setOpenExportModal}
        agentData={exportAgentData}
      />
      {exportApiAgent && (
        <ExportApiModal
          open={openExportApiModal}
          setOpen={setOpenExportApiModal}
          agentId={exportApiAgent.agentId}
          agentName={exportApiAgent.agentName}
          version={exportApiAgent.version}
          environment={activeTab.toLowerCase() as "uat" | "prod"}
          deployId={exportApiAgent.deployId}
        />
      )}
      <Dialog
        open={!!toggleConfirm}
        onOpenChange={(next) => {
          if (!next) setToggleConfirm(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {toggleConfirm
                ? toggleConfirm.kind === "status"
                  ? toggleConfirm.nextValue
                    ? t("Start agent?")
                    : t("Stop agent?")
                  : toggleConfirm.nextValue
                    ? t("Enable agent?")
                    : t("Disable agent?")
                : ""}
            </DialogTitle>
            <DialogDescription>
              {toggleConfirm
                ? toggleConfirm.kind === "status"
                  ? toggleConfirm.nextValue
                    ? t(
                        'Are you sure you want to start "{{name}}"?',
                        { name: toggleConfirm.agentName },
                      )
                    : t(
                        'Are you sure you want to stop "{{name}}"?',
                        { name: toggleConfirm.agentName },
                      )
                  : toggleConfirm.nextValue
                    ? t(
                        'Are you sure you want to enable "{{name}}"?',
                        { name: toggleConfirm.agentName },
                      )
                    : t(
                        'Are you sure you want to disable "{{name}}"?',
                        { name: toggleConfirm.agentName },
                      )
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setToggleConfirm(null)}
            >
              {t("Cancel")}
            </Button>
            <Button
              onClick={async () => {
                const pending = toggleConfirm;
                if (!pending) return;
                setToggleConfirm(null);
                if (pending.kind === "status") {
                  await handleStatusToggle(pending.workflowId);
                } else {
                  await handleEnabledToggle(pending.workflowId);
                }
              }}
            >
              {t("Yes, continue")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={promoteDialogOpen} onOpenChange={setPromoteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("Move UAT to PROD")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
              {requiresProdApproval
                ? t(
                    "This action will stop the agent in UAT first, then send the PROD move for approval.",
                  )
                : t(
                    "This action will stop the agent in UAT first and move it directly to PROD.",
                  )}
            </div>
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              {requiresProdApproval
                ? t(
                    "Until approval is completed, this deployment will remain stopped in UAT.",
                  )
                : t(
                    "The UAT deployment will be marked stopped in the database at the same time as the PROD move.",
                  )}
            </div>
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="promote-public"
                  checked={selectedPromoteVisibility === "PUBLIC"}
                  onCheckedChange={(checked) => {
                    if (checked === true) {
                      setSelectedPromoteVisibility("PUBLIC");
                    }
                  }}
                />
                <Label htmlFor="promote-public">{t("Public")}</Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="promote-private"
                  checked={selectedPromoteVisibility === "PRIVATE"}
                  onCheckedChange={(checked) => {
                    if (checked === true) {
                      setSelectedPromoteVisibility("PRIVATE");
                    }
                  }}
                />
                <Label htmlFor="promote-private">{t("Private")}</Label>
              </div>
            </div>
            {isSuperAdmin && selectedPromoteVisibility === "PRIVATE" && (
              <div className="space-y-2 rounded-md border p-3">
                <Label className="text-sm font-medium">
                  {t("Department")}
                </Label>
                <Select
                  value={selectedPromoteDepartmentId}
                  onValueChange={setSelectedPromoteDepartmentId}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={t("Select a department")} />
                  </SelectTrigger>
                  <SelectContent>
                    {promoteDepartments.map((dept) => (
                      <SelectItem key={dept.id} value={dept.id}>
                        {dept.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t("All users in this department will be able to access this PROD deployment.")}
                </p>
              </div>
            )}
            {selectedPromoteVisibility === "PRIVATE" && (
              <div className="space-y-2 rounded-md border p-3">
                <Label htmlFor="promote-emails" className="text-sm font-medium">
                  {t("Assigned users")}
                </Label>
                <div className="rounded-md border bg-background px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {normalizedPromoteEmails.map((email) => (
                      <span
                        key={email}
                        className="inline-flex items-center gap-1 rounded-full border bg-slate-100 px-2 py-1 text-xs text-slate-700"
                      >
                        <span className="max-w-[220px] truncate">{email}</span>
                        <button
                          type="button"
                          onClick={() => removePromoteEmail(email)}
                          className="rounded p-0.5 text-slate-500 hover:bg-slate-200 hover:text-slate-700"
                          aria-label={`Remove ${email}`}
                        >
                          <span className="text-xxs leading-none">x</span>
                        </button>
                      </span>
                    ))}
                    <input
                      id="promote-emails"
                      value={promoteEmailDraft}
                      onChange={(event) =>
                        setPromoteEmailDraft(event.target.value)
                      }
                      onKeyDown={(event) => {
                        if (
                          ["Enter", "Tab", ",", ";", " "].includes(event.key)
                        ) {
                          if (!promoteEmailDraft.trim()) return;
                          event.preventDefault();
                          addPromoteEmails(promoteEmailDraft);
                          setPromoteEmailDraft("");
                          return;
                        }
                        if (
                          event.key === "Backspace" &&
                          !promoteEmailDraft.trim() &&
                          normalizedPromoteEmails.length > 0
                        ) {
                          const lastEmail =
                            normalizedPromoteEmails[
                              normalizedPromoteEmails.length - 1
                            ];
                          if (lastEmail) removePromoteEmail(lastEmail);
                        }
                      }}
                      onBlur={() => {
                        if (promoteEmailDraft.trim()) {
                          addPromoteEmails(promoteEmailDraft);
                          setPromoteEmailDraft("");
                        }
                      }}
                      onPaste={(event) => {
                        const pasted = event.clipboardData.getData("text");
                        if (!pasted) return;
                        if (/[,;\n\s]/.test(pasted)) {
                          event.preventDefault();
                          addPromoteEmails(pasted);
                        }
                      }}
                      placeholder={
                        normalizedPromoteEmails.length === 0
                          ? "Type email and press Enter"
                          : "Add more users"
                      }
                      className="min-w-[180px] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    />
                  </div>
                  {promoteEmailDraft.trim().length > 0 && (
                    <div className="mt-2 rounded-md border bg-white shadow-sm">
                      {isFetchingPromoteEmailSuggestions ? (
                        <div className="px-3 py-2 text-xs text-muted-foreground">
                          Searching users...
                        </div>
                      ) : promoteEmailSuggestions.length > 0 ? (
                        <div className="max-h-44 overflow-auto py-1">
                          {promoteEmailSuggestions.map((item) => (
                            <button
                              key={item.email}
                              type="button"
                              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-100"
                              onMouseDown={(event) => {
                                event.preventDefault();
                                addPromoteEmails(item.email);
                                setPromoteEmailDraft("");
                              }}
                            >
                              <span className="truncate">{item.email}</span>
                              {item.display_name && (
                                <span className="ml-2 truncate text-xs text-muted-foreground">
                                  {item.display_name}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="px-3 py-2 text-xs text-muted-foreground">
                          No department suggestions found.
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {t(
                    "Private PROD visibility: only assigned users, creator and admins can access.",
                  )}
                </p>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setPromoteDialogOpen(false)}
              >
                {t("Cancel")}
              </Button>
              <Button
                onClick={() => void handlePromoteToProd()}
                disabled={
                  !selectedPromoteDeployId ||
                  promotingById[selectedPromoteDeployId]
                }
              >
                {promotingById[selectedPromoteDeployId]
                  ? t("Moving...")
                  : t("Move")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={sharingDialogOpen} onOpenChange={setSharingDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {t("Sharing Options")}
              {selectedSharingAgentName ? ` - ${selectedSharingAgentName}` : ""}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
              {t(
                "Update shared users for this deployed agent only. Other Control Panel settings remain unchanged.",
              )}
            </div>
            <div className="space-y-2 rounded-md border p-3">
              <Label htmlFor="sharing-emails" className="text-sm font-medium">
                {t("Business/User Email IDs (optional)")}
              </Label>
              <div className="rounded-md border bg-background px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  {normalizedSharingEmails.map((email) => (
                    <span
                      key={email}
                      className="inline-flex items-center gap-1 rounded-full border bg-slate-100 px-2 py-1 text-xs text-slate-700"
                    >
                      <span className="max-w-[220px] truncate">{email}</span>
                      <button
                        type="button"
                        onClick={() => removeSharingEmail(email)}
                        className="rounded p-0.5 text-slate-500 hover:bg-slate-200 hover:text-slate-700"
                        aria-label={`Remove ${email}`}
                      >
                        <span className="text-xxs leading-none">x</span>
                      </button>
                    </span>
                  ))}
                  <input
                    id="sharing-emails"
                    value={sharingEmailDraft}
                    onChange={(event) => setSharingEmailDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (["Enter", "Tab", ",", ";", " "].includes(event.key)) {
                        if (!sharingEmailDraft.trim()) return;
                        event.preventDefault();
                        addSharingEmails(sharingEmailDraft);
                        setSharingEmailDraft("");
                        return;
                      }
                      if (
                        event.key === "Backspace" &&
                        !sharingEmailDraft.trim() &&
                        normalizedSharingEmails.length > 0
                      ) {
                        const lastEmail =
                          normalizedSharingEmails[normalizedSharingEmails.length - 1];
                        if (lastEmail) removeSharingEmail(lastEmail);
                      }
                    }}
                    onBlur={() => {
                      if (sharingEmailDraft.trim()) {
                        addSharingEmails(sharingEmailDraft);
                        setSharingEmailDraft("");
                      }
                    }}
                    onPaste={(event) => {
                      const pasted = event.clipboardData.getData("text");
                      if (!pasted) return;
                      if (/[,;\n\s]/.test(pasted)) {
                        event.preventDefault();
                        addSharingEmails(pasted);
                      }
                    }}
                    placeholder={
                      normalizedSharingEmails.length === 0
                        ? "Type email to search and press Enter to add"
                        : "Add another email"
                    }
                    className="min-w-[180px] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                  />
                </div>
                {sharingEmailDraft.trim().length > 0 && (
                  <div className="mt-2 rounded-md border bg-background shadow-sm">
                    {isFetchingSharingEmailSuggestions ? (
                      <div className="px-3 py-2 text-xs text-muted-foreground">
                        Searching users...
                      </div>
                    ) : sharingEmailSuggestions.length > 0 ? (
                      <div className="max-h-44 overflow-auto py-1">
                        {sharingEmailSuggestions.map((item) => (
                          <button
                            key={item.email}
                            type="button"
                            className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-muted"
                            onMouseDown={(event) => {
                              event.preventDefault();
                              addSharingEmails(item.email);
                              setSharingEmailDraft("");
                            }}
                          >
                            <span className="w-full truncate text-sm text-foreground">
                              {item.email}
                            </span>
                            {item.display_name && (
                              <span className="w-full truncate text-xs text-muted-foreground">
                                {item.display_name}
                              </span>
                            )}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="px-3 py-2 text-xs text-muted-foreground">
                        No department suggestions found.
                      </div>
                    )}
                  </div>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {t(
                  "Outlook-style recipients. Suggestions come from saved department emails for this agent.",
                )}
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setSharingDialogOpen(false)}
              >
                {t("Cancel")}
              </Button>
              <Button
                onClick={() => void handleSaveSharing()}
                disabled={savingSharing || updateSharingMutation.isPending}
              >
                {savingSharing || updateSharingMutation.isPending
                  ? t("Saving...")
                  : t("Save sharing")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <EmbedModal
        open={openEmbedModal}
        setOpen={setOpenEmbedModal}
        agentId={selectedSharingAgentId}
        agentName={selectedSharingAgentName}
        environment={selectedSharingEnvironment}
        version={selectedSharingVersion}
        isAuth={isAuth}
        tweaksBuildedObject={{}}
        activeTweaks={false}
      />
    </div>
  );
}
