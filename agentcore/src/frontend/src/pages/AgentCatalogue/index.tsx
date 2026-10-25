import { Copy, Eye, Filter, Search, Star, X } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import SemanticSearchToggle from "@/components/common/semanticSearchToggle";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AuthContext } from "@/contexts/authContext";
import {
  useGetRegistry,
  useGetRegistryRatings,
  usePostRegistryRate,
  type RegistryEntry,
} from "@/controllers/API/queries/registry";
import { useSemanticSearch } from "@/controllers/API/queries/semantic-search/use-semantic-search";
import CustomLoader from "@/customization/components/custom-loader";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useAlertStore from "@/stores/alertStore";
import CopyAgentDialog from "@/components/agents/copy-agent-dialog";

interface AgentCatalogueViewProps {
  setSearch?: (search: string) => void;
}

type FilterTab = "creator" | "department" | "version" | "rating" | "tags";

const formatRegistryBadgeLabel = (agent: RegistryEntry) => {
  if (agent.version_label) return agent.version_label;
  if (!agent.version_number) return "";
  return agent.version_number;
};

export default function AgentCatalogueView({
  setSearch,
}: AgentCatalogueViewProps): JSX.Element {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState("");
  const [semanticEnabled, setSemanticEnabled] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [activeFilterTab, setActiveFilterTab] =
    useState<FilterTab>("creator");
  const [selectedCreator, setSelectedCreator] = useState("all");
  const [selectedDepartment, setSelectedDepartment] = useState("all");
  const [selectedVersion, setSelectedVersion] = useState("all");
  const [selectedRating, setSelectedRating] = useState("all");
  const [selectedTagFilter, setSelectedTagFilter] = useState("all");
  const [selectedEntry, setSelectedEntry] = useState<RegistryEntry | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [ratingOpen, setRatingOpen] = useState(false);
  const [score, setScore] = useState(5);
  const [scoreInput, setScoreInput] = useState("5");

  const { permissions } = useContext(AuthContext);
  const navigate = useCustomNavigate();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  const getIdentityDisplay = (nameLike?: string | null, emailLike?: string | null) => {
    const normalizedName = nameLike?.trim() || "";
    if (normalizedName && !normalizedName.includes("@")) return normalizedName;
    const normalizedEmail = emailLike?.trim() || "";
    if (normalizedEmail) return normalizedEmail.split("@", 1)[0];
    if (normalizedName) {
      return normalizedName.includes("@")
        ? normalizedName.split("@", 1)[0]
        : normalizedName;
    }
    return t("Unknown");
  };

  const getIdentityEmail = (nameLike?: string | null, emailLike?: string | null) => {
    const normalizedEmail = emailLike?.trim() || "";
    if (normalizedEmail) return normalizedEmail;
    const normalizedName = nameLike?.trim() || "";
    return normalizedName.includes("@") ? normalizedName : "";
  };

  const { data: registryData, isLoading: isLoadingRegistry } = useGetRegistry(
    {
      search: (!semanticEnabled && searchQuery) ? searchQuery : undefined,
      page: 1,
      page_size: semanticEnabled ? 100 : 60,
      deployment_env: "PROD",
    },
    {
      refetchInterval: 30000,
      keepPreviousData: true,
    },
  );

  const { data: semanticData, isLoading: isLoadingSemantic, isError: isErrorSemantic } = useSemanticSearch(
    semanticEnabled && searchQuery
      ? { entity_type: "agents", q: searchQuery, top_k: 60, registry_only: true }
      : null,
    { enabled: semanticEnabled && !!searchQuery },
  );
  const { data: ratingsData, refetch: refetchRatings } = useGetRegistryRatings(
    { registry_id: selectedEntry?.id || "" },
    { enabled: ratingOpen && !!selectedEntry?.id },
  );
  const rateMutation = usePostRegistryRate();

  // When semantic search is active, get the map of matched agent IDs → scores
  // to filter and rank real registry entries (match by agent_id field)
  const semanticAgentScores = useMemo(() => {
    if (!semanticEnabled || !searchQuery || !semanticData?.results) return null;
    return new Map(semanticData.results.map((item) => [item.id, item.score]));
  }, [semanticEnabled, searchQuery, semanticData]);

  const filteredAgents = useMemo(() => {
    let items = registryData?.items || [];

    // When semantic search is active, filter registry entries to only those
    // whose underlying agent_id matches a semantic search result
    if (semanticAgentScores && semanticAgentScores.size > 0) {
      items = items.filter((agent) => semanticAgentScores.has(agent.agent_id));
      // Sort by semantic relevance score (highest first)
      items = [...items].sort((a, b) =>
        (semanticAgentScores.get(b.agent_id) ?? 0) - (semanticAgentScores.get(a.agent_id) ?? 0)
      );
    } else if (semanticEnabled && searchQuery && semanticAgentScores?.size === 0) {
      // Semantic search returned no results
      items = [];
    }

    return items.filter((agent) => {
      const creatorName = (
        agent.listed_by_username?.trim() ||
        agent.listed_by_email?.trim() ||
        ""
      );
      const departmentName = agent.department_name?.trim() || "";
      const versionName = agent.version_label?.trim() || agent.version_number?.trim() || "";
      const tags = agent.tags || [];
      const ratingValue = Number(agent.rating || 0);

      const matchesCreator =
        selectedCreator === "all" ||
        (selectedCreator === "__none__"
          ? !creatorName
          : creatorName === selectedCreator);
      const matchesDepartment =
        selectedDepartment === "all" ||
        (selectedDepartment === "__none__"
          ? !departmentName
          : departmentName === selectedDepartment);
      const matchesVersion =
        selectedVersion === "all" || versionName === selectedVersion;
      const matchesRating =
        selectedRating === "all" ||
        (selectedRating === "4+" && ratingValue >= 4) ||
        (selectedRating === "3+" && ratingValue >= 3) ||
        (selectedRating === "below3" && ratingValue < 3);
      const matchesTag =
        selectedTagFilter === "all" || tags.includes(selectedTagFilter);

      return (
        matchesCreator &&
        matchesDepartment &&
        matchesVersion &&
        matchesRating &&
        matchesTag
      );
    });
  }, [
    registryData?.items,
    semanticAgentScores,
    semanticEnabled,
    searchQuery,
    selectedCreator,
    selectedDepartment,
    selectedRating,
    selectedTagFilter,
    selectedVersion,
  ]);

  const availableTags = useMemo(() => {
    const tagSet = new Set<string>();
    (registryData?.items || []).forEach((agent) => {
      (agent.tags || []).forEach((tag: string) => tagSet.add(tag));
    });
    return Array.from(tagSet).sort();
  }, [registryData?.items]);

  const creatorOptions = useMemo(() => {
    const names = new Set<string>();
    (registryData?.items || []).forEach((agent) => {
      const creator =
        agent.listed_by_username?.trim() || agent.listed_by_email?.trim() || "";
      if (creator) names.add(creator);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [registryData?.items]);

  const departmentOptions = useMemo(() => {
    const names = new Set<string>();
    (registryData?.items || []).forEach((agent) => {
      const department = agent.department_name?.trim() || "";
      if (department) names.add(department);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [registryData?.items]);

  const versionOptions = useMemo(() => {
    const names = new Set<string>();
    (registryData?.items || []).forEach((agent) => {
      const version = agent.version_label?.trim() || agent.version_number?.trim() || "";
      if (version) names.add(version);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [registryData?.items]);

  const clearFilters = () => {
    setSelectedCreator("all");
    setSelectedDepartment("all");
    setSelectedVersion("all");
    setSelectedRating("all");
    setSelectedTagFilter("all");
  };

  const activeFilterChips = useMemo(() => {
    const chips: Array<{ key: string; label: string; onRemove: () => void }> =
      [];
    if (selectedCreator !== "all") {
      chips.push({
        key: "creator",
        label:
          selectedCreator === "__none__"
            ? "Creator: Unknown"
            : `Creator: ${selectedCreator}`,
        onRemove: () => setSelectedCreator("all"),
      });
    }
    if (selectedDepartment !== "all") {
      chips.push({
        key: "department",
        label:
          selectedDepartment === "__none__"
            ? "Department: None"
            : `Department: ${selectedDepartment}`,
        onRemove: () => setSelectedDepartment("all"),
      });
    }
    if (selectedVersion !== "all") {
      chips.push({
        key: "version",
        label: `Version: ${selectedVersion}`,
        onRemove: () => setSelectedVersion("all"),
      });
    }
    if (selectedRating !== "all") {
      const ratingLabelMap: Record<string, string> = {
        "4+": "Rating: 4.0+",
        "3+": "Rating: 3.0+",
        below3: "Rating: Below 3.0",
      };
      chips.push({
        key: "rating",
        label: ratingLabelMap[selectedRating] ?? `Rating: ${selectedRating}`,
        onRemove: () => setSelectedRating("all"),
      });
    }
    if (selectedTagFilter !== "all") {
      chips.push({
        key: "tag",
        label: `Tag: ${selectedTagFilter}`,
        onRemove: () => setSelectedTagFilter("all"),
      });
    }
    return chips;
  }, [
    selectedCreator,
    selectedDepartment,
    selectedRating,
    selectedTagFilter,
    selectedVersion,
  ]);

  useEffect(() => {
    if (!setSearch) return;
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  const openCloneModal = (entry: RegistryEntry) => {
    setSelectedEntry(entry);
    setCloneOpen(true);
  };

  const openRatingModal = (entry: RegistryEntry) => {
    setSelectedEntry(entry);
    setRatingOpen(true);
    setScore(5);
    setScoreInput("5");
  };

  const handleRate = async () => {
    try {
      if (!selectedEntry) return;
      await rateMutation.mutateAsync({
        registry_id: selectedEntry.id,
        score,
      });
      await refetchRatings();
      setSuccessData({ title: t("Rating submitted successfully") });
      setRatingOpen(false);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to submit rating"),
        list: [error?.response?.data?.detail || t("Please try again")],
      });
    }
  };

  const handleScoreChange = (raw: string) => {
    let next = raw.replace(/[^\d.]/g, "");
    if (next.includes(".")) {
      const [intPart, ...rest] = next.split(".");
      next = `${intPart}.${rest.join("")}`;
    }
    next = next.replace(/^0+(?=\d)/, "");
    if (next === "") {
      setScoreInput("");
      return;
    }
    const parsed = Number(next);
    if (Number.isNaN(parsed)) {
      setScoreInput("");
      return;
    }
    const clamped = Math.min(5, Math.max(1, parsed));
    setScore(clamped);
    setScoreInput(Number.isInteger(clamped) ? String(clamped) : String(clamped));
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("Agent Registry")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t(
              "Discover and deploy pre-built AI agents and workflows. Clone, customize, and integrate into your applications.",
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={semanticEnabled ? t("Semantic search agents...") : t("Search agents")}
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
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setActiveFilterTab("creator");
              setShowFilters(true);
            }}
          >
            <Filter className="mr-1.5 h-4 w-4" />
            {t("Filters")}
          </Button>
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
            {t("Clear all")}
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
                <h2 className="text-lg font-semibold">{t("Filters")}</h2>
                <div className="flex items-center gap-3">
                  <button
                    onClick={clearFilters}
                    className="text-sm text-primary hover:underline"
                  >
                    {t("Clear Filters")}
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
                        {t("People")}
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
                          {t("Creator")}
                        </button>
                        <button
                          onClick={() => setActiveFilterTab("department")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "department"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          {t("Department")}
                        </button>
                      </div>
                    </div>

                    <div>
                      <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("Registry")}
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
                          {t("Version")}
                        </button>
                        <button
                          onClick={() => setActiveFilterTab("rating")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "rating"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          {t("Rating")}
                        </button>
                        <button
                          onClick={() => setActiveFilterTab("tags")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "tags"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          {t("Tags")}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex-1 overflow-auto p-5">
                  {activeFilterTab === "creator" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">{t("Creator")}</h3>
                      <select
                        value={selectedCreator}
                        onChange={(e) => setSelectedCreator(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">{t("All creators")}</option>
                        <option value="__none__">{t("Unknown creator")}</option>
                        {creatorOptions.map((creator) => (
                          <option key={creator} value={creator}>
                            {creator}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "department" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">{t("Department")}</h3>
                      <select
                        value={selectedDepartment}
                        onChange={(e) => setSelectedDepartment(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">{t("All departments")}</option>
                        <option value="__none__">{t("No department")}</option>
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
                      <h3 className="text-sm font-semibold">{t("Version")}</h3>
                      <select
                        value={selectedVersion}
                        onChange={(e) => setSelectedVersion(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">{t("All versions")}</option>
                        {versionOptions.map((version) => (
                          <option key={version} value={version}>
                            {version}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "rating" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">{t("Rating")}</h3>
                      <select
                        value={selectedRating}
                        onChange={(e) => setSelectedRating(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">{t("All ratings")}</option>
                        <option value="4+">{t("4.0 and above")}</option>
                        <option value="3+">{t("3.0 and above")}</option>
                        <option value="below3">{t("Below 3.0")}</option>
                      </select>
                    </div>
                  )}

                  {activeFilterTab === "tags" && (
                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold">{t("Tags")}</h3>
                      <select
                        value={selectedTagFilter}
                        onChange={(e) => setSelectedTagFilter(e.target.value)}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="all">{t("All tags")}</option>
                        {availableTags.map((tag) => (
                          <option key={tag} value={tag}>
                            {tag}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      <div className="flex-1 overflow-auto p-4 sm:p-6">
        {isLoadingRegistry ? (
          <div className="flex h-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : filteredAgents.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-12 text-center">
            <p className="text-muted-foreground">{t("No registry agents found")}</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {filteredAgents.map((agent) => (
                <div
                  key={agent.id}
                  className="group relative overflow-hidden rounded-lg border bg-card transition-all hover:border-primary/50"
                >
                  <div className="p-6">
                    <div className="mb-4 flex items-start gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex items-center gap-2">
                          <h3 className="truncate text-lg font-semibold">
                            {agent.title}
                          </h3>
                          {agent.version_number && (
                            <span className="inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-xxs font-semibold text-muted-foreground">
                              {formatRegistryBadgeLabel(agent)}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {(() => {
                            const displayName = getIdentityDisplay(
                              agent.listed_by_username,
                              agent.listed_by_email,
                            );
                            const hoverEmail = getIdentityEmail(
                              agent.listed_by_username,
                              agent.listed_by_email,
                            );
                            return (
                              <>
                                {t("by")}{" "}
                                {hoverEmail ? (
                                  <ShadTooltip content={hoverEmail}>
                                    <span className="cursor-help">{displayName}</span>
                                  </ShadTooltip>
                                ) : (
                                  displayName
                                )}
                                {agent.department_name && (
                                  <>
                                    {" · "}
                                    <span className="text-muted-foreground">{agent.department_name}</span>
                                  </>
                                )}
                                {agent.organization_name && (
                                  <>
                                    {" · "}
                                    <span className="text-muted-foreground">{agent.organization_name}</span>
                                  </>
                                )}
                              </>
                            );
                          })()}
                        </p>
                      </div>
                    </div>

                    <p className="mb-4 line-clamp-2 text-sm text-muted-foreground">
                      {agent.summary || t("No description available.")}
                    </p>

                    {(agent.tags || []).length > 0 && (
                      <div
                        className="relative mb-4 flex flex-wrap gap-1.5 group/tags"
                      >
                        {(agent.tags || []).slice(0, 3).map((tag: string, idx: number) => (
                          <Badge
                            key={`${agent.id}-${idx}`}
                            variant="outline"
                            className="text-xs px-2 py-0.5"
                          >
                            {tag}
                          </Badge>
                        ))}
                        {(agent.tags || []).length > 3 && (
                          <Badge variant="outline" className="text-xs px-2 py-0.5 cursor-default">
                            +{(agent.tags || []).length - 3}
                          </Badge>
                        )}
                        {/* Full tags tooltip on hover */}
                        {(agent.tags || []).length > 3 && (
                          <div className="absolute bottom-full left-0 mb-1 hidden group-hover/tags:flex flex-wrap gap-1 bg-popover border rounded-lg p-2 shadow-lg z-50 w-max max-w-[300px]">
                            {(agent.tags || []).map((tag: string, idx: number) => (
                              <Badge
                                key={`tooltip-${agent.id}-${idx}`}
                                variant="outline"
                                className="text-xs px-2 py-0.5"
                              >
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    <div className="flex items-center justify-between border-t pt-4">
                      <ShadTooltip
                        content={
                          !can("copy_agents")
                            ? t("You don't have permission to view ratings")
                            : t("Click to rate and view reviews")
                        }
                      >
                        <button
                          type="button"
                          onClick={() =>
                            can("copy_agents") && openRatingModal(agent)
                          }
                          className={`flex items-center gap-1.5 text-sm ${!can("copy_agents") ? "cursor-not-allowed opacity-50" : ""}`}
                          disabled={!can("copy_agents")}
                        >
                          <Star className="h-4 w-4 fill-yellow-500 text-yellow-500" />
                          <span className="font-medium">
                            {Number(agent.rating || 0).toFixed(1)}
                          </span>
                          <span className="text-muted-foreground">
                            ({agent.rating_count || 0})
                          </span>
                        </button>
                      </ShadTooltip>

                      <div className="flex items-center gap-2">
                        <ShadTooltip
                          content={
                            !can("view_registry_agent")
                              ? t("You don't have permission to view")
                              : ""
                          }
                        >
                          <span className="inline-block">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={!can("view_registry_agent")}
                              onClick={() =>
                                navigate(`/agent-catalogue/${agent.id}/view`)
                              }
                            >
                              <Eye className="mr-1.5 h-3.5 w-3.5" />
                              {t("View")}
                            </Button>
                          </span>
                        </ShadTooltip>

                        <ShadTooltip
                          content={
                            !can("copy_agents")
                              ? t("You don't have permission to copy")
                              : ""
                          }
                        >
                          <span className="inline-block">
                            <Button
                              size="sm"
                              disabled={!can("copy_agents")}
                              onClick={() => openCloneModal(agent)}
                            >
                              <Copy className="mr-1.5 h-3.5 w-3.5" />
                              {t("Copy")}
                            </Button>
                          </span>
                        </ShadTooltip>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-6 text-center text-sm text-muted-foreground">
              {t("Showing {{shown}} of {{total}} agents", {
                shown: filteredAgents.length,
                total: registryData?.total || 0,
              })}
            </div>
          </>
        )}
      </div>

      <CopyAgentDialog
        open={cloneOpen}
        onOpenChange={setCloneOpen}
        source={
          selectedEntry
            ? {
                type: "registry",
                registryId: selectedEntry.id,
                title: selectedEntry.title,
              }
            : null
        }
        onSuccess={(agentId, projectId) =>
          navigate(`/agent/${agentId}/folder/${projectId}`)
        }
      />

      <Dialog open={ratingOpen} onOpenChange={setRatingOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("Rate Agent")}</DialogTitle>
            <DialogDescription>
              {t("Submit your rating and review for this registry agent.")}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 text-sm">
            <div>
              <span className="mb-1 block text-xs text-muted-foreground">
                {t("Score (1 to 5)")}
              </span>
              <input
                type="number"
                min={1}
                max={5}
                step={0.5}
                value={scoreInput}
                onChange={(e) => handleScoreChange(e.target.value)}
                className="w-full rounded-md border bg-card px-3 py-2"
              />
            </div>
            <div className="rounded-md border bg-muted/30 p-3">
              <p className="text-xs text-muted-foreground">
                {t("Average:")}{" "}
                {Number(
                  ratingsData?.average_rating || selectedEntry?.rating || 0,
                ).toFixed(1)}{" "}
                | {t("Total ratings:")} 
                {ratingsData?.total_ratings || selectedEntry?.rating_count || 0}
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRatingOpen(false)}>
              {t("Close")}
            </Button>
            <Button onClick={handleRate} disabled={rateMutation.isLoading}>
              {rateMutation.isLoading ? t("Submitting...") : t("Submit Rating")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
