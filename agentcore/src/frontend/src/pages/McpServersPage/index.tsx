import { useContext, useEffect, useRef, useState } from "react";
import {
  Plus,
  Server,
  MoreVertical,
  Edit2,
  Trash2,
  Search,
  XCircle,
  Plug,
  ChevronDown,
  ChevronRight,
  Loader2,
  Wrench,
} from "lucide-react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import Loading from "@/components/ui/loading";
import { Switch } from "@/components/ui/switch";
import { useDeleteMCPServer } from "@/controllers/API/queries/mcp/use-delete-mcp-server";
import { useGetMCPServers } from "@/controllers/API/queries/mcp/use-get-mcp-servers";
import { usePatchMCPServer } from "@/controllers/API/queries/mcp/use-patch-mcp-server";
import { useProbeMCPServer } from "@/controllers/API/queries/mcp/use-probe-mcp-server";
import AddMcpServerModal from "@/modals/mcpServerModal";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import { AuthContext } from "@/contexts/authContext";
import useAlertStore from "@/stores/alertStore";
import type { McpRegistryType, McpProbeResponse } from "@/types/mcp";
import { api } from "@/controllers/API/api";

import { useTranslation } from "react-i18next";

export default function MCPServersPage() {
  const { t } = useTranslation();
  const { permissions, userData, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const normalizedRole = String(role || "").toLowerCase().replace(" ", "_");
  const { data: servers, isLoading } = useGetMCPServers({ active_only: false });
  const deleteMutation = useDeleteMCPServer();
  const patchMutation = usePatchMCPServer();
  const probeMutation = useProbeMCPServer();
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const [searchQuery, setSearchQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editServer, setEditServer] = useState<McpRegistryType | null>(null);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [serverToDelete, setServerToDelete] = useState<McpRegistryType | null>(null);

  // Probe state
  const [probeResults, setProbeResults] = useState<Record<string, McpProbeResponse>>({});
  const [probingServerId, setProbingServerId] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [visibilityOptions, setVisibilityOptions] = useState<{
    departments: { id: string; name: string; org_id: string }[];
  }>({ departments: [] });

  // Toggle state (tracks which servers are currently being toggled)
  const [togglingServerId, setTogglingServerId] = useState<string | null>(null);
  const ENV_BADGE_CLASSES: Record<string, string> = {
    uat: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    prod: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    both: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  };
  const VISIBILITY_LABELS: Record<string, string> = {
    private: "Private",
    department: "Department",
    organization: "Organization",
  };
  const VISIBILITY_BADGE_CLASSES: Record<string, string> = {
    private: "bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-400",
    department: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400",
    organization: "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400",
  };
  const formatEnvLabel = (server: McpRegistryType) => {
    const envs = (server.environments || []).map((env) => String(env).toLowerCase());
    if (envs.includes("uat") && envs.includes("prod")) return "UAT + PROD";
    if (envs.length > 0) return envs[0].toUpperCase();
    return String(server.deployment_env || "UAT").toUpperCase();
  };
  const getEnvBadgeClass = (server: McpRegistryType) => {
    const envs = (server.environments || []).map((env) => String(env).toLowerCase());
    if (envs.includes("uat") && envs.includes("prod")) return ENV_BADGE_CLASSES.both;
    if (envs.length > 0) return ENV_BADGE_CLASSES[envs[0]] ?? "bg-gray-100 text-gray-700";
    const fallback = String(server.deployment_env || "uat").toLowerCase();
    return ENV_BADGE_CLASSES[fallback] ?? "bg-gray-100 text-gray-700";
  };
  const getVisibilityLabel = (server: McpRegistryType) => {
    if (server.visibility === "public") {
      if (server.public_scope === "organization") return VISIBILITY_LABELS.organization;
      return VISIBILITY_LABELS.department;
    }
    return VISIBILITY_LABELS.private;
  };
  const getVisibilityBadgeClass = (server: McpRegistryType) => {
    if (server.visibility === "public") {
      if (server.public_scope === "organization") return VISIBILITY_BADGE_CLASSES.organization;
      return VISIBILITY_BADGE_CLASSES.department;
    }
    return VISIBILITY_BADGE_CLASSES.private;
  };
  const getDepartmentScopeLabel = (server: McpRegistryType) => {
    const deptNameById = new Map(
      visibilityOptions.departments.map((dept) => [dept.id, dept.name]),
    );
    if (server.visibility === "public" && server.public_scope === "organization") {
      return t("All departments");
    }
    const deptIds =
      server.visibility === "public" && server.public_scope === "department"
        ? server.public_dept_ids?.length
          ? server.public_dept_ids
          : server.dept_id
            ? [server.dept_id]
            : []
        : server.dept_id
          ? [server.dept_id]
          : [];
    if (deptIds.length === 0) return "-";
    const names = deptIds.map((id) => deptNameById.get(id) || id);
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  };

  const handleEdit = (server: McpRegistryType) => {
    if (!canEditMcp(server)) return;
    setEditServer(server);
    setEditOpen(true);
  };

  const handleDelete = async (server: McpRegistryType) => {
    if (!canDeleteMcp(server)) return;
    try {
      await deleteMutation.mutateAsync({ id: server.id });
      setSuccessData({
        title: t("MCP server deleted"),
        list: [t("{{name}} was removed.", { name: server.server_name })],
      });
    } catch (e: any) {
      setErrorData({ title: t("Delete failed"), list: [e.message] });
    }
  };

  const openDeleteModal = (server: McpRegistryType) => {
    if (!canDeleteMcp(server)) return;
    setServerToDelete(server);
    setDeleteModalOpen(true);
  };

  const handleToggleActive = async (server: McpRegistryType) => {
    if (server.approval_status === "pending") {
      setErrorData({
        title: t("Approval pending"),
        list: [t("This MCP server cannot be connected or disconnected until the approval is completed.")],
      });
      return;
    }
    const newActive = !server.is_active;
    setTogglingServerId(server.id);
    try {
      await patchMutation.mutateAsync({
        id: server.id,
        data: { is_active: newActive },
      });
      setSuccessData({
        title: newActive ? t("MCP server connected") : t("MCP server disconnected"),
        list: [t("{{name}}", { name: server.server_name })],
      });
      // Clear probe result when disconnecting
      if (!newActive) {
        setProbeResults((prev) => {
          const next = { ...prev };
          delete next[server.id];
          return next;
        });
        setExpandedRows((prev) => {
          const next = new Set(prev);
          next.delete(server.id);
          return next;
        });
      }
    } catch (e: any) {
      setErrorData({ title: t("Update failed"), list: [e.message] });
    } finally {
      setTogglingServerId(null);
    }
  };

  const handleProbe = async (server: McpRegistryType) => {
    if (server.approval_status === "pending") {
      setErrorData({
        title: t("Approval pending"),
        list: [t("This MCP server cannot be refreshed until the approval is completed.")],
      });
      return;
    }
    setProbingServerId(server.id);
    try {
      const result = await probeMutation.mutateAsync({ id: server.id });
      setProbeResults((prev) => ({ ...prev, [server.id]: result }));
      if (result.success) {
        setSuccessData({
          title: t("Connection successful"),
          list: [t("Found {{count}} tool(s).", { count: result.tools_count ?? 0 })],
        });
      } else {
        setErrorData({ title: t("Connection failed"), list: [result.message] });
      }
    } catch (e: any) {
      setProbeResults((prev) => ({
        ...prev,
        [server.id]: { success: false, message: e.message },
      }));
      setErrorData({ title: t("Probe failed"), list: [e.message] });
    } finally {
      setProbingServerId(null);
    }
  };

  const toggleRowExpand = (serverId: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(serverId)) {
        next.delete(serverId);
      } else {
        next.add(serverId);
      }
      return next;
    });
  };

  // Filter servers based on search
  const filteredServers = servers?.filter(
    (server) =>
      !searchQuery ||
      server.server_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      server.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const canAddMcp = can("add_new_mcp");
  const canRequestMcp = can("request_new_mcp");
  const isRoot = normalizedRole === "root";
  const isSuperAdmin = normalizedRole === "super_admin";
  const isDepartmentAdmin = normalizedRole === "department_admin";
  const isMcpAdmin = isRoot || isSuperAdmin || isDepartmentAdmin;
  const canSeeActions = isMcpAdmin && (can("edit_mcp") || can("delete_mcp"));
  const currentUserId = userData?.id;
  const userDeptId = userData?.department_id ?? null;
  const userDeptIds = userDeptId ? [userDeptId] : [];

  const isDeptScopedForUser = (server: McpRegistryType) => {
    if (userDeptIds.length === 0) return false;
    const deptIdSet = new Set(userDeptIds);
    if (server.visibility === "public" && server.public_scope === "department") {
      if (server.public_dept_ids?.some((id) => deptIdSet.has(id))) return true;
      if (server.dept_id && deptIdSet.has(server.dept_id)) return true;
    }
    if (server.visibility === "private") {
      if (server.dept_id && deptIdSet.has(server.dept_id)) return true;
    }
    return false;
  };

  const isMultiDeptMcp = (server: McpRegistryType) => (server.public_dept_ids?.length ?? 0) > 1;

  const canEditMcp = (server: McpRegistryType) => {
    if (!isMcpAdmin || !can("edit_mcp")) return false;
    if (server.approval_status === "pending") return false;
    if (isRoot || isSuperAdmin) return true;
    if (isDepartmentAdmin) {
      if (isMultiDeptMcp(server)) return false;
      if (server.visibility === "public" && server.public_scope === "organization") return false;
      return Boolean(
        currentUserId &&
          (isDeptScopedForUser(server) ||
            server.reviewed_by === currentUserId ||
            (server.created_by_id === currentUserId && server.approval_status === "approved")),
      );
    }
    return false;
  };

  const canDeleteMcp = (server: McpRegistryType) => {
    if (!isMcpAdmin || !can("delete_mcp")) return false;
    if (server.approval_status === "pending") return false;
    if (isRoot || isSuperAdmin) return true;
    if (isDepartmentAdmin) {
      if (isMultiDeptMcp(server)) return false;
      if (server.visibility === "public" && server.public_scope === "organization") return false;
      return Boolean(
        currentUserId &&
          (isDeptScopedForUser(server) ||
            server.reviewed_by === currentUserId ||
            (server.created_by_id === currentUserId && server.approval_status === "approved")),
      );
    }
    return false;
  };

  useEffect(() => {
    if (!isMcpAdmin) return;
    api
      .get("api/mcp/registry/visibility-options")
      .then((res) => {
        setVisibilityOptions({ departments: res.data?.departments || [] });
      })
      .catch(() => {
        setVisibilityOptions({ departments: [] });
      });
  }, [isMcpAdmin]);

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
      {/* Header - Fixed */}
      <div className="flex flex-shrink-0 flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("MCP Servers")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Manage MCP Servers for use in your agents")}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Search Bar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search servers...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring sm:w-64"
            />
          </div>

          {canAddMcp ? (
            <Button
              variant="default"
              onClick={() => setAddOpen(true)}
              data-testid="add-mcp-server-button-page"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t("Add MCP Server")}
            </Button>
          ) : canRequestMcp ? (
            <Button
              variant="default"
              onClick={() => setRequestOpen(true)}
              data-testid="request-mcp-server-button-page"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t("Request MCP Server")}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Table - Scrollable */}
      <style>{`
        .mcp-table-scroll::-webkit-scrollbar { height: 0; }
        .mcp-table-scroll { scrollbar-width: none; }
        .mcp-mirror-bar::-webkit-scrollbar { height: 8px; }
        .mcp-mirror-bar::-webkit-scrollbar-track { background: hsl(var(--muted)); border-radius: 9999px; }
        .mcp-mirror-bar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground)); border-radius: 9999px; }
        .mcp-mirror-bar::-webkit-scrollbar-thumb:hover { background: hsl(var(--foreground) / 0.8); }
        .mcp-mirror-bar { scrollbar-width: thin; scrollbar-color: hsl(var(--muted-foreground)) hsl(var(--muted)); }
      `}</style>
      <div className="flex-1 flex flex-col overflow-hidden p-4 sm:p-6 gap-3">
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border bg-card">
          <div ref={tableScrollRef} className="mcp-table-scroll flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        ) : filteredServers && filteredServers.length === 0 ? (
          <div className="flex h-full w-full items-center justify-center">
            <div className="text-center">
              <Server className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <h3 className="mt-4 text-lg font-semibold">{t("No MCP servers found")}</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                {searchQuery
                  ? t("No servers match your search criteria")
                  : t("Get started by adding your first MCP server")}
              </p>
            </div>
          </div>
        ) : (
              <table className="w-full min-w-[1000px]">
                <thead className="sticky top-0 z-10 bg-card shadow-sm">
                  <tr className="border-b border-border">
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Server Name")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Mode")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Environment")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Visibility")}
                    </th>
                    {isDepartmentAdmin ? (
                      <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                        {t("Created By")}
                      </th>
                    ) : null}
                    {isSuperAdmin ? (
                      <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                        {t("Department Scope")}
                      </th>
                    ) : null}
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Status")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Connection")}
                    </th>
                    {canSeeActions ? (
                      <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                        {t("Actions")}
                      </th>
                    ) : null}
                  </tr>
                </thead>

                <tbody className="divide-y divide-border">
                  {filteredServers?.map((server) => (
                    (() => {
                      const isAwaitingApproval = server.approval_status === "pending";
                      const controlsDisabled = isAwaitingApproval;
                      const approvalBadge =
                        server.approval_status === "pending"
                          ? { label: t("Awaiting Approval"), cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" }
                          : server.approval_status === "rejected"
                            ? { label: t("Rejected"), cls: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" }
                            : { label: t("Approved"), cls: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" };
                      return (
                    <>
                      <tr key={server.id} className="group hover:bg-muted/50">
                        {/* Server Name */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${server.is_active ? "bg-orange-100 dark:bg-orange-900/30" : "bg-muted"}`}>
                              <ForwardedIconComponent
                                name="Mcp"
                                className={`h-5 w-5 ${server.is_active ? "text-orange-600 dark:text-orange-400" : "text-muted-foreground"}`}
                              />
                            </div>
                            <div className={server.is_active ? "" : "opacity-50"}>
                              <div className="flex items-center gap-2">
                                <div
                                  className="max-w-[260px] line-clamp-2 font-semibold leading-6"
                                  title={server.server_name}
                                >
                                  {server.server_name}
                                </div>
                                {server.approval_status !== "approved" && (
                                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xxs font-medium ${approvalBadge.cls}`}>
                                    {approvalBadge.label}
                                  </span>
                                )}
                              </div>
                              {server.description && (
                                <div
                                  className="mt-0.5 text-xs text-muted-foreground line-clamp-1"
                                  title={server.description}
                                >
                                  {server.description}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Mode */}
                        <td className="px-6 py-4">
                          <span className="inline-flex rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium uppercase">
                            {server.mode}
                          </span>
                        </td>

                        {/* Environment */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium uppercase ${getEnvBadgeClass(
                              server,
                            )}`}
                          >
                            {formatEnvLabel(server)}
                          </span>
                        </td>

                        {/* Visibility */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${getVisibilityBadgeClass(
                              server,
                            )}`}
                          >
                            {t(getVisibilityLabel(server))}
                          </span>
                        </td>
                        {isDepartmentAdmin ? (
                          <td className="px-6 py-4 text-sm text-muted-foreground">
                            <div
                              className="max-w-[170px] truncate"
                              title={server.created_by_email || server.created_by || "-"}
                            >
                              {server.created_by || "-"}
                            </div>
                          </td>
                        ) : null}
                        {isSuperAdmin ? (
                          <td className="px-6 py-4 text-sm text-muted-foreground">
                            <span
                              className="inline-block max-w-[160px] truncate text-sm text-muted-foreground"
                              title={getDepartmentScopeLabel(server)}
                            >
                              {getDepartmentScopeLabel(server)}
                            </span>
                          </td>
                        ) : null}

                        {/* Status - Toggle Switch */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={server.is_active}
                              onCheckedChange={() => handleToggleActive(server)}
                              disabled={togglingServerId === server.id || controlsDisabled}
                              className="data-[state=checked]:bg-green-600"
                            />
                            <span className={`text-xs font-medium ${server.is_active ? "text-green-600" : "text-muted-foreground"}`}>
                              {controlsDisabled
                                ? t("Awaiting Approval")
                                : server.is_active
                                  ? t("Connected")
                                  : t("Disconnected")}
                            </span>
                          </div>
                        </td>

                        {/* Connection - Probe */}
                        <td className="px-6 py-4">
                          {(() => {
                            const cachedTools = server.tools_snapshot ?? [];
                            const latestProbe = probeResults[server.id];
                            const liveTools = latestProbe?.success ? latestProbe.tools ?? [] : [];
                            const hasCachedTools = cachedTools.length > 0;
                            const hasLiveTools = liveTools.length > 0;
                            const cachedToolCount =
                              server.tools_count ?? (hasCachedTools ? cachedTools.length : null);
                            const toolCount =
                              latestProbe?.success
                                ? (latestProbe.tools_count ?? cachedToolCount)
                                : cachedToolCount;
                            const canExpand = hasLiveTools || hasCachedTools;
                            const isExpanded = expandedRows.has(server.id);
                            const showWrench = toolCount != null && canExpand;
                            const hasFailedRefresh = Boolean(latestProbe && !latestProbe.success);
                            return (
                              <>
                                {controlsDisabled ? (
                                  <span className="text-xs text-muted-foreground">
                                    {t("Awaiting approval")}
                                  </span>
                                ) : !server.is_active ? (
                                  <span className="text-xs text-muted-foreground">
                                    {t("--")}
                                  </span>
                                ) : probingServerId === server.id ? (
                                  <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    {t("Refreshing...")}
                                  </span>
                                ) : (
                                  <div className="flex items-center gap-2">
                                    {hasFailedRefresh ? (
                                      <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-600">
                                        <XCircle className="h-3.5 w-3.5" />
                                        {t("Last refresh failed")}
                                      </span>
                                    ) : toolCount != null ? (
                                      <span className="inline-flex items-center gap-1 text-xs font-medium text-green-600">
                                        <Plug className="h-3.5 w-3.5" />
                                        {t("Verified")}
                                      </span>
                                    ) : null}
                                    {showWrench && (
                                      <button
                                        onClick={() => toggleRowExpand(server.id)}
                                        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted"
                                      >
                                        <Wrench className="h-3 w-3" />
                                        {toolCount} {t("tools")}
                                        {isExpanded ? (
                                          <ChevronDown className="h-3 w-3" />
                                        ) : (
                                          <ChevronRight className="h-3 w-3" />
                                        )}
                                      </button>
                                    )}
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => handleProbe(server)}
                                      className="h-7 text-xs"
                                      disabled={controlsDisabled}
                                    >
                                      <Plug className="mr-1 h-3.5 w-3.5" />
                                      {toolCount != null ? t("Refresh Connection") : t("Test Connection")}
                                    </Button>
                                  </div>
                                )}
                              </>
                            );
                          })()}
                        </td>

                        {/* Actions */}
                        {canSeeActions ? (
                          <td className="px-6 py-4">
                            {canEditMcp(server) || canDeleteMcp(server) ? (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <button
                                    className="flex h-8 w-8 items-center justify-center rounded-md transition-colors hover:bg-accent disabled:cursor-not-allowed"
                                    data-testid={`mcp-server-menu-button-${server.server_name}`}
                                    disabled={controlsDisabled}
                                  >
                                    <MoreVertical className="h-4 w-4 text-foreground" />
                                  </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  {canEditMcp(server) && (
                                    <DropdownMenuItem
                                      onClick={() => handleEdit(server)}
                                    >
                                      <Edit2 className="mr-2 h-4 w-4" />
                                      {t("Edit")}
                                    </DropdownMenuItem>
                                  )}
                                  {canDeleteMcp(server) && (
                                    <DropdownMenuItem
                                      onClick={() => openDeleteModal(server)}
                                      className="text-destructive"
                                    >
                                      <Trash2 className="mr-2 h-4 w-4" />
                                      {t("Delete")}
                                    </DropdownMenuItem>
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            ) : (
                              <span className="text-xs text-muted-foreground">--</span>
                            )}
                          </td>
                        ) : null}
                      </tr>

                      {/* Expandable tool list */}
                      {expandedRows.has(server.id) &&
                        ((probeResults[server.id]?.success &&
                          probeResults[server.id]?.tools &&
                          probeResults[server.id].tools!.length > 0) ||
                          (server.tools_snapshot && server.tools_snapshot.length > 0)) && (
                          <tr key={`${server.id}-tools`} className="bg-muted/30">
                            <td colSpan={6 + (isDepartmentAdmin ? 1 : 0) + (isSuperAdmin ? 1 : 0) + (canSeeActions ? 1 : 0)} className="px-6 py-3">
                              <div className="ml-[52px] space-y-1">
                                <div className="mb-2 text-xs font-medium text-muted-foreground">
                                  {t("Discovered Tools:")}
                                </div>
                                {((probeResults[server.id]?.success
                                  ? probeResults[server.id]?.tools
                                  : null) ?? server.tools_snapshot ?? []).map((tool) => (
                                  <div
                                    key={tool.name}
                                    className="flex items-start gap-2 py-1"
                                  >
                                    <Wrench className="mt-0.5 h-3 w-3 flex-shrink-0 text-muted-foreground" />
                                    <div>
                                      <span className="text-sm font-medium">
                                        {tool.name}
                                      </span>
                                      {tool.description && (
                                        <p className="text-xs text-muted-foreground">
                                          {tool.description}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </td>
                          </tr>
                        )}
                    </>
                      );
                    })()
                  ))}
                </tbody>
              </table>
        )}
          </div>
          <div ref={mirrorRef} className="mcp-mirror-bar flex-shrink-0 overflow-x-scroll overflow-y-hidden border-t" style={{ height: 12 }}>
            <div ref={phantomRef} style={{ height: 1 }} />
          </div>
        </div>
        <div className="text-center text-sm text-muted-foreground flex-shrink-0">
          {t("Showing {{shown}} of {{total}} servers", {
            shown: filteredServers?.length || 0,
            total: servers?.length || 0,
          })}
        </div>
      </div>

      {/* Modals */}
      <AddMcpServerModal open={addOpen} setOpen={setAddOpen} />
      <AddMcpServerModal open={requestOpen} setOpen={setRequestOpen} requestMode />
      {editOpen && editServer && (
        <AddMcpServerModal
          open={editOpen}
          setOpen={setEditOpen}
          initialData={editServer}
        />
      )}
      <DeleteConfirmationModal
        open={deleteModalOpen}
        setOpen={setDeleteModalOpen}
        onConfirm={() => {
          if (serverToDelete) handleDelete(serverToDelete);
          setDeleteModalOpen(false);
          setServerToDelete(null);
        }}
        description={t("MCP Server")}
      />
    </div>
  );
}
