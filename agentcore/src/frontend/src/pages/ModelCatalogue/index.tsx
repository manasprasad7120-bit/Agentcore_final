import {
  Plus,
  MoreVertical,
  Edit2,
  Trash2,
  Search,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
} from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import SemanticSearchToggle from "@/components/common/semanticSearchToggle";
import type { ModelType, ModelEnvironment, ModelTypeFilter } from "@/types/models/models";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import EditModelModal from "./components/edit-model-modal";
import RequestModelModal from "./components/request-model-modal";
import { getProviderIcon } from "@/utils/logo_provider";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import useAlertStore from "@/stores/alertStore";
import { useTranslation } from "react-i18next";
import {
  useGetRegistryModels,
  useDeleteRegistryModel,
} from "@/controllers/API/queries/models";
import { useSemanticSearch } from "@/controllers/API/queries/semantic-search/use-semantic-search";

type ProviderFilter = "all" | string;
type EnvFilter = "all" | ModelEnvironment;
type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
};

const PROVIDER_LABELS: Record<string, string> = {
  all: "All",
  openai: "OpenAI",
  azure: "Azure",
  anthropic: "Anthropic",
  google: "Google",
  groq: "Groq",
  openai_compatible: "Custom",
};

const ENV_LABELS: Record<string, string> = {
  all: "All Envs",
  uat: "UAT",
  prod: "PROD",
};

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

const MODEL_TYPE_LABELS: Record<string, string> = {
  llm: "LLMs",
  embedding: "Embeddings",
};

export default function ModelCatalogue(): JSX.Element {
  const { t } = useTranslation();
  const [modelTypeFilter, setModelTypeFilter] = useState<ModelTypeFilter>("llm");
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>("all");
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [semanticEnabled, setSemanticEnabled] = useState(false);

  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isRequestModalOpen, setIsRequestModalOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ModelType | null>(null);
  const [deleteConfirmModel, setDeleteConfirmModel] = useState<ModelType | null>(null);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });

  const { permissions, role, userData } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const normalizedRole = (role ?? "").toLowerCase().replace(" ", "_");
  const isRoot = normalizedRole === "root";
  const isModelAdmin =
    isRoot || normalizedRole === "super_admin" || normalizedRole === "department_admin";
  const canAddModel = isModelAdmin && can("add_new_model");
  const canRequestModel = can("request_new_model");
  const isDepartmentAdmin = normalizedRole === "department_admin";
  const isSuperAdmin = normalizedRole === "super_admin";
  const currentUserId = userData?.id;
  const userDeptId = userData?.department_id ?? null;
  const canSeeActions = isModelAdmin && (can("edit_model") || can("delete_model"));

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

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
    // Also observe the inner content so the phantom re-syncs when the table
    // widens after async data arrives. The outer container's size doesn't
    // change on data load, so without this the mirror scrollbar stays missing
    // on initial mount until the user resizes the window or sidebar.
    const inner = scroll.firstElementChild as Element | null;
    if (inner) ro.observe(inner);
    // One deferred resync after the next paint to catch late layout (e.g. when
    // data is cached and the table renders synchronously after this effect).
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

  // Fetch models from API
  const { data: models, isLoading, isError } = useGetRegistryModels({
    active_only: false,
  });

  const { data: semanticData, isLoading: isLoadingSemantic, isError: isErrorSemantic } = useSemanticSearch(
    semanticEnabled && searchQuery
      ? { entity_type: "models", q: searchQuery, top_k: 60, registry_only: true }
      : null,
    { enabled: semanticEnabled && !!searchQuery },
  );

  const deleteMutation = useDeleteRegistryModel();

  useEffect(() => {
    api
      .get("api/models/registry/visibility-options")
      .then((res) => {
        const options: VisibilityOptions = res.data || {
          organizations: [],
          departments: [],
        };
        setVisibilityOptions(options);
      })
      .catch(() => {
        setVisibilityOptions({ organizations: [], departments: [] });
      });
  }, []);

  const deptById = useMemo(
    () =>
      new Map(
        visibilityOptions.departments.map((dept) => [dept.id, dept] as const),
      ),
    [visibilityOptions.departments],
  );


  const displayModels = models ?? [];
  const defaultProviders = (Object.keys(PROVIDER_LABELS) as ProviderFilter[]).filter(
    (p) => p !== "all",
  );
  const dataProviders = Array.from(new Set(displayModels.map((m) => m.provider))).filter(
    (p) => !defaultProviders.includes(p),
  );
  const availableProviders: ProviderFilter[] = ["all", ...defaultProviders, ...dataProviders.sort()];

  /* ---------------------------------- Filtering ---------------------------------- */

  // Build semantic score map for ranking
  const semanticScores = semanticEnabled && searchQuery && semanticData?.results
    ? new Map(semanticData.results.map((r) => [r.id, r.score]))
    : null;

  const filteredModels = (() => {
    let result = displayModels.filter((model) => {
      const matchesType = model.model_type === modelTypeFilter;
      const matchesProvider =
        providerFilter === "all" || model.provider === providerFilter;
      const normalizeEnv = (env: string) => (env === "test" ? "uat" : env);
      const modelEnvs = (model.environments ?? []).map((env) => normalizeEnv(String(env).toLowerCase()));
      const fallbackEnv = normalizeEnv(String(model.environment ?? "").toLowerCase());
      const effectiveEnvs = modelEnvs.length ? modelEnvs : fallbackEnv ? [fallbackEnv] : [];
      const matchesEnv =
        envFilter === "all" || effectiveEnvs.includes(envFilter);

      const matchesSearch = semanticScores
        ? semanticScores.has(model.id)
        : !searchQuery ||
          model.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          model.model_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          model.description?.toLowerCase().includes(searchQuery.toLowerCase());

      return matchesType && matchesProvider && matchesEnv && matchesSearch;
    });
    // Sort by semantic relevance score when active (highest first)
    if (semanticScores) {
      result = [...result].sort((a, b) =>
        (semanticScores.get(b.id) ?? 0) - (semanticScores.get(a.id) ?? 0)
      );
    }
    return result;
  })();

  /* ---------------------------------- Helpers ---------------------------------- */

  const getProviderLogo = (provider: string) => {
    const iconSrc = getProviderIcon(provider);
    return (
      <img
        src={iconSrc}
        alt={`${provider} icon`}
        className="h-4 w-4 object-contain"
      />
    );
  };

  const getProviderName = (provider: string) =>
    PROVIDER_LABELS[provider] ?? provider;

  const userDeptIds = useMemo(() => {
    if (userDeptId) return [userDeptId];
    return visibilityOptions.departments.map((d) => d.id);
  }, [userDeptId, visibilityOptions.departments]);

  const isDeptScopedForUser = (model: ModelType) => {
    if (userDeptIds.length === 0) return false;
    const deptIdSet = new Set(userDeptIds);
    if (model.visibility_scope === "department") {
      if (model.public_dept_ids?.some((id) => deptIdSet.has(id))) return true;
      if (model.dept_id && deptIdSet.has(model.dept_id)) return true;
    }
    if (model.visibility_scope === "private") {
      if (model.dept_id && deptIdSet.has(model.dept_id)) return true;
    }
    return false;
  };

  const isMultiDeptModel = (model: ModelType) => (model.public_dept_ids?.length ?? 0) > 1;

  const getEnvironmentLabel = (model: ModelType) => {
    const normalizeEnv = (env: string) => (env === "test" ? "uat" : env);
    const modelEnvs = (model.environments ?? []).map((env) => normalizeEnv(String(env).toLowerCase()));
    const fallbackEnv = normalizeEnv(String(model.environment ?? "").toLowerCase());
    const effectiveEnvs = modelEnvs.length ? modelEnvs : fallbackEnv ? [fallbackEnv] : [];
    const sorted = Array.from(new Set(effectiveEnvs)).sort();
    if (sorted.length > 1) return "UAT + PROD";
    return ENV_LABELS[sorted[0]] ?? sorted[0]?.toUpperCase() ?? "-";
  };

  const getEnvironmentBadgeClass = (model: ModelType) => {
    const normalizeEnv = (env: string) => (env === "test" ? "uat" : env);
    const modelEnvs = (model.environments ?? []).map((env) => normalizeEnv(String(env).toLowerCase()));
    const fallbackEnv = normalizeEnv(String(model.environment ?? "").toLowerCase());
    const effectiveEnvs = modelEnvs.length ? modelEnvs : fallbackEnv ? [fallbackEnv] : [];
    const sorted = Array.from(new Set(effectiveEnvs)).sort();
    if (sorted.length > 1) return ENV_BADGE_CLASSES.both;
    return ENV_BADGE_CLASSES[sorted[0]] ?? "bg-gray-100 text-gray-700";
  };

  const canEditModel = (model: ModelType) => {
    if (!isModelAdmin || !can("edit_model")) return false;
    if (model.approval_status === "pending") return false;
    if (isRoot || isSuperAdmin) return true;
    if (isDepartmentAdmin) {
      if (isMultiDeptModel(model)) return false;
      return Boolean(
        currentUserId &&
          (isDeptScopedForUser(model) ||
            model.reviewed_by === currentUserId ||
            (model.created_by_id === currentUserId && model.approval_status === "approved")),
      );
    }
    return false;
  };

  const canDeleteModel = (model: ModelType) => {
    if (!isModelAdmin || !can("delete_model")) return false;
    if (model.approval_status === "pending") return false;
    if (isRoot || isSuperAdmin) return true;
    if (isDepartmentAdmin) {
      if (isMultiDeptModel(model)) return false;
      return Boolean(
        currentUserId &&
          (isDeptScopedForUser(model) ||
            model.reviewed_by === currentUserId ||
            (model.created_by_id === currentUserId && model.approval_status === "approved")),
      );
    }
    return false;
  };

  const handleDeleteConfirm = async () => {
    if (!deleteConfirmModel) return;
    try {
      await deleteMutation.mutateAsync({ id: deleteConfirmModel.id });
      setSuccessData({
        title: t("Model \"{{name}}\" deleted.", { name: deleteConfirmModel.display_name }),
      });
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        t("You do not have permission to delete this model.");
      setErrorData({ title: t("Failed to delete model."), list: [detail] });
    }
    setDeleteConfirmModel(null);
  };

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("Model Registry")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Onboard, browse, and manage AI models across environments")}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={semanticEnabled ? t("Semantic search models...") : t("Search models...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border bg-card py-2.5 pl-10 pr-4 text-sm sm:w-64"
            />
          </div>
          <SemanticSearchToggle
            enabled={semanticEnabled}
            onToggle={setSemanticEnabled}
            isSearching={isLoadingSemantic && semanticEnabled && !!searchQuery}
          />

          {canAddModel ? (
            <ShadTooltip
              content={
                !canAddModel
                  ? t("You don't have permission to add models")
                  : ""
              }
            >
              <span className="inline-block">
                <Button
                  onClick={() => {
                    setSelectedModel(null);
                    setIsEditModalOpen(true);
                  }}
                  disabled={!canAddModel}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {modelTypeFilter === "embedding" ? t("Add Embedding") : t("Add Model")}
                </Button>
              </span>
            </ShadTooltip>
          ) : canRequestModel ? (
            <Button onClick={() => setIsRequestModalOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {modelTypeFilter === "embedding" ? t("Request Embedding") : t("Request Model")}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Filters */}
      <div className="flex-shrink-0 border-b px-4 py-4 sm:px-6 md:px-8">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t("Model Type")}
            </p>
            <div className="flex gap-2">
              {(["llm", "embedding"] as ModelTypeFilter[]).map((type) => (
                <Button
                  key={type}
                  size="sm"
                  variant={modelTypeFilter === type ? "default" : "outline"}
                  className="flex-1"
                  onClick={() => setModelTypeFilter(type)}
                >
                  {t(MODEL_TYPE_LABELS[type])}
                </Button>
              ))}
            </div>
          </div>

          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t("Provider")}
            </p>
            <Select
              value={providerFilter}
              onValueChange={(value) => setProviderFilter(value)}
            >
              <SelectTrigger className="w-full bg-card">
                <SelectValue placeholder={t("All")} />
              </SelectTrigger>
              <SelectContent>
                {availableProviders.map((provider) => (
                  <SelectItem key={provider} value={provider}>
                    {t(getProviderName(provider))}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t("Environment")}
            </p>
            <Select
              value={envFilter}
              onValueChange={(value) => setEnvFilter(value as EnvFilter)}
            >
              <SelectTrigger className="w-full bg-card">
                <SelectValue placeholder={t("All Envs")} />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ENV_LABELS) as EnvFilter[]).map((env) => (
                  <SelectItem key={env} value={env}>
                    {t(ENV_LABELS[env])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-end">
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                setProviderFilter("all");
                setEnvFilter("all");
                setSearchQuery("");
              }}
            >
              {t("Reset Filters")}
            </Button>
          </div>
        </div>
      </div>

      {/* Table */}
      <style>{`
        /* hide only the horizontal native scrollbar on the outer container */
        .model-table-scroll::-webkit-scrollbar { height: 0; }
        .model-table-scroll { scrollbar-width: none; }
        /* styled sticky mirror bar */
        .model-mirror-bar::-webkit-scrollbar { height: 8px; }
        .model-mirror-bar::-webkit-scrollbar-track { background: hsl(var(--muted)); border-radius: 9999px; }
        .model-mirror-bar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground)); border-radius: 9999px; }
        .model-mirror-bar::-webkit-scrollbar-thumb:hover { background: hsl(var(--foreground) / 0.8); }
        .model-mirror-bar { scrollbar-width: thin; scrollbar-color: hsl(var(--muted-foreground)) hsl(var(--muted)); }
      `}</style>
      <div className="flex-1 flex flex-col overflow-hidden p-4 sm:p-6 gap-3">
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border bg-card">
          <div ref={tableScrollRef} className="model-table-scroll flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center py-20 text-destructive">
            {t("Failed to load models. Please try again.")}
          </div>
        ) : (
          <>
            <table style={{ width: "max-content", minWidth: "100%" }} className="">
                <thead className="sticky top-0 z-10 bg-card shadow-sm">
                  <tr className="border-b border-border">
                    {[
                      "Model",
                      "Provider",
                      "Model ID",
                      "Environment",
                      "Visibility",
                      ...(isDepartmentAdmin ? ["Created By"] : []),
                      ...(isSuperAdmin ? ["Department Scope"] : []),
                      "Type",
                      "RPM",
                      "TPM",
                      "Status",
                      "Available In",
                    ...(canSeeActions ? ["Actions"] : []),
                    ].map((h) => (
                      <th
                        key={h}
                        className={`px-4 py-4 text-left text-xs font-medium uppercase tracking-wider ${
                          h === "Model"
                            ? "w-[22%] min-w-[220px]"
                            : h === "Model ID"
                              ? "w-[18%] min-w-[220px]"
                              : h === "Provider"
                                ? "w-[10%] min-w-[120px]"
                                : h === "Department Scope"
                                  ? "w-[8%] min-w-[110px]"
                                  : h === "Environment" || h === "Visibility" || h === "Type" || h === "Status"
                                    ? "w-[7%] min-w-[90px]"
                                    : h === "RPM" || h === "TPM"
                                      ? "w-[6%] min-w-[80px]"
                                      : h === "Actions"
                                        ? "w-[5%] min-w-[64px]"
                                        : ""
                        }`}
                      >
                        {t(h)}
                      </th>
                    ))}
                  </tr>
                </thead>

                <tbody className="divide-y">
                  {filteredModels.length === 0 ? (
                    <tr>
                      <td
                        colSpan={11 + (isDepartmentAdmin ? 1 : 0) + (isSuperAdmin ? 1 : 0) + (canSeeActions ? 1 : 0)}
                        className="px-6 py-12 text-center text-sm text-muted-foreground"
                      >
                        {displayModels.length === 0
                          ? t("No models onboarded yet. Click 'Add Model' to get started.")
                          : t("No models match the current filters.")}
                      </td>
                    </tr>
                  ) : (
                    filteredModels.map((model) => (
                      <tr key={model.id} className="group hover:bg-muted/50">
                        {/* Model Name */}
                        <td className="w-[22%] min-w-[220px] px-4 py-4 align-middle">
                          <div
                            className="max-w-[300px] line-clamp-2 font-semibold leading-6"
                            title={model.display_name}
                          >
                            {model.display_name}
                          </div>
                          {model.description && (
                            <div
                              className="mt-0.5 max-w-[300px] text-xs text-muted-foreground line-clamp-1"
                              title={model.description}
                            >
                              {model.description}
                            </div>
                          )}
                        </td>

                        {/* Provider */}
                        <td className="w-[10%] min-w-[120px] px-4 py-4">
                          <div className="flex items-center gap-2">
                            <div className="flex h-8 w-8 items-center justify-center rounded border">
                              {getProviderLogo(model.provider)}
                            </div>
                            <span className="truncate text-sm">
                              {t(getProviderName(model.provider))}
                            </span>
                          </div>
                        </td>

                        {/* Model ID */}
                        <td className="w-[18%] min-w-[220px] px-4 py-4 align-middle">
                          <div
                            className="max-w-[260px] truncate text-sm font-mono text-muted-foreground"
                            title={model.model_name}
                          >
                            {model.model_name}
                          </div>
                        </td>

                        {/* Environment */}
                        <td className="w-[7%] min-w-[90px] px-4 py-4">
                          <span
                            className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium uppercase ${
                              getEnvironmentBadgeClass(model)
                            }`}
                          >
                            {t(getEnvironmentLabel(model))}
                          </span>
                        </td>

                        {/* Visibility */}
                        <td className="w-[7%] min-w-[90px] px-4 py-4">
                          <span
                            className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
                              VISIBILITY_BADGE_CLASSES[model.visibility_scope ?? "private"] ??
                              "bg-gray-100 text-gray-700"
                            }`}
                          >
                            {t(
                              VISIBILITY_LABELS[model.visibility_scope ?? "private"] ??
                                model.visibility_scope ??
                                "Private",
                            )}
                          </span>
                        </td>

                        {isDepartmentAdmin && (
                          <td className="px-4 py-4 text-sm text-muted-foreground">
                            <div
                              className="max-w-[150px] truncate"
                              title={model.created_by_email || model.created_by || "-"}
                            >
                              {model.created_by || "-"}
                            </div>
                          </td>
                        )}

                        {isSuperAdmin && (
                          <td className="w-[8%] min-w-[110px] px-4 py-4 text-sm text-muted-foreground">
                            <div
                              className="max-w-[140px] truncate"
                              title={(() => {
                                if (model.visibility_scope === "organization") {
                                  return "All departments";
                                }
                                if (model.public_dept_ids && model.public_dept_ids.length > 0) {
                                  const names = model.public_dept_ids.map((id) => deptById.get(id)?.name ?? id);
                                  return names.join(", ");
                                }
                                if (model.dept_id) {
                                  const dept = deptById.get(model.dept_id);
                                  if (dept) {
                                    return dept.name;
                                  }
                                  return model.dept_id;
                                }
                                return "-";
                              })()}
                            >
                              {(() => {
                              if (model.visibility_scope === "organization") {
                                return "All departments";
                              }
                              if (model.public_dept_ids && model.public_dept_ids.length > 0) {
                                const names = model.public_dept_ids.map((id) => deptById.get(id)?.name ?? id);
                                return names.length > 2
                                  ? `${names.slice(0, 2).join(", ")} +${names.length - 2}`
                                  : names.join(", ");
                              }
                              if (model.dept_id) {
                                const dept = deptById.get(model.dept_id);
                                if (dept) {
                                  return dept.name;
                                }
                                return model.dept_id;
                              }
                              return "-";
                            })()}
                            </div>
                          </td>
                        )}

                        {/* Type */}
                        <td className="w-[7%] min-w-[90px] px-4 py-4">
                          <span
                            className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
                              model.model_type === "embedding"
                                ? "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"
                                : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                            }`}
                          >
                            {model.model_type === "embedding" ? t("Embedding") : t("LLM")}
                          </span>
                        </td>

                        {/* RPM */}
                        <td className="w-[6%] min-w-[80px] px-4 py-4 text-sm text-muted-foreground">
                          {model.rate_limit_rpm
                            ? model.rate_limit_rpm.toLocaleString()
                            : <span className="text-xs italic">{t("Unlimited")}</span>}
                        </td>

                        {/* TPM */}
                        <td className="w-[6%] min-w-[80px] px-4 py-4 text-sm text-muted-foreground">
                          {model.rate_limit_tpm
                            ? model.rate_limit_tpm.toLocaleString()
                            : <span className="text-xs italic">{t("Unlimited")}</span>}
                        </td>

                        {/* Status */}
                        <td className="w-[7%] min-w-[90px] px-4 py-4">
                          {model.approval_status === "pending" ? (
                            <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-yellow-600">
                              <Clock className="h-3.5 w-3.5" />
                              {t("Pending Approval")}
                            </span>
                          ) : model.approval_status === "rejected" ? (
                            <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-red-600">
                              <XCircle className="h-3.5 w-3.5" />
                              {t("Rejected")}
                            </span>
                          ) : model.is_active ? (
                            <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-green-600">
                              <CheckCircle className="h-3.5 w-3.5" />
                              {t("Active")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-muted-foreground">
                              <XCircle className="h-3.5 w-3.5" />
                              {t("Inactive")}
                            </span>
                          )}
                        </td>

                        {/* Show In */}
                        <td className="px-4 py-4">
                          <div className="flex gap-1">
                            {((model as any).show_in || ["orchestrator", "agent"]).includes("orchestrator") && (
                              <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                                {t("Orch")}
                              </span>
                            )}
                            {((model as any).show_in || ["orchestrator", "agent"]).includes("agent") && (
                              <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                                {t("Agent")}
                              </span>
                            )}
                          </div>
                        </td>

                        {canSeeActions ? (
                          <td className="w-[5%] min-w-[64px] px-4 py-4">
                            {canEditModel(model) || canDeleteModel(model) ? (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <button className="rounded p-1 hover:bg-muted">
                                    <MoreVertical className="h-4 w-4" />
                                  </button>
                                </DropdownMenuTrigger>

                                <DropdownMenuContent align="end">
                                  {canEditModel(model) ? (
                                    <DropdownMenuItem
                                      onClick={() => {
                                        setSelectedModel(model);
                                        setIsEditModalOpen(true);
                                      }}
                                    >
                                      <Edit2 className="mr-2 h-4 w-4" />
                                      {t("Edit")}
                                    </DropdownMenuItem>
                                  ) : null}

                                  {canEditModel(model) && canDeleteModel(model) ? (
                                    <DropdownMenuSeparator />
                                  ) : null}

                                  {canDeleteModel(model) ? (
                                    <DropdownMenuItem
                                      className="text-destructive"
                                      onClick={() => setDeleteConfirmModel(model)}
                                    >
                                      <Trash2 className="mr-2 h-4 w-4" />
                                      {t("Delete")}
                                    </DropdownMenuItem>
                                  ) : null}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            ) : (
                              <span className="text-xs text-muted-foreground">-</span>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
          </>
        )}
          </div>
          {/* mirror — sticks at the bottom edge of the box */}
          <div
            ref={mirrorRef}
            className="model-mirror-bar flex-shrink-0 overflow-x-scroll overflow-y-hidden border-t"
            style={{ height: 12 }}
          >
            <div ref={phantomRef} style={{ height: 1 }} />
          </div>
        </div>
        <div className="text-center text-sm text-muted-foreground flex-shrink-0">
          {t("Showing {{shown}} of {{total}} models", {
            shown: filteredModels.length,
            total: displayModels.length,
          })}
        </div>
      </div>

      {/* Edit/Create Modal */}
      <EditModelModal
        open={isEditModalOpen}
        onOpenChange={setIsEditModalOpen}
        model={selectedModel}
        modelType={modelTypeFilter}
      />
      <RequestModelModal
        open={isRequestModalOpen}
        onOpenChange={setIsRequestModalOpen}
        modelType={modelTypeFilter}
      />

      {/* Delete Confirmation Dialog */}
      {deleteConfirmModel && (
        <>
          <div
            className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm"
            onClick={() => setDeleteConfirmModel(null)}
          />
          <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-card p-6 shadow-lg">
            <h3 className="text-lg font-semibold">{t("Delete Model")}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("Are you sure you want to delete {{name}}? This action cannot be undone.", {
                name: deleteConfirmModel.display_name,
              })}
            </p>
            <div className="mt-6 flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setDeleteConfirmModel(null)}
              >
                {t("Cancel")}
              </Button>
              <Button
                variant="destructive"
                className="flex-1"
                onClick={handleDeleteConfirm}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                {t("Delete")}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
