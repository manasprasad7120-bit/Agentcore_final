import { Plus, Folder, MoreVertical, Edit2, Trash2, FileText, X, Info, Copy, Check, Search, Bot, Tag } from "lucide-react";
import { useFolderStore } from "@/stores/foldersStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { usePostFolders } from "@/controllers/API/queries/folders";
import useAlertStore from "@/stores/alertStore";
import { track } from "@/customization/utils/analytics";
import type { FolderType } from "@/pages/MainPage/entities";
import type { AgentType } from "@/types/agent";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { AuthContext } from "@/contexts/authContext";
import SemanticSearchToggle from "@/components/common/semanticSearchToggle";
import { useSemanticSearch } from "@/controllers/API/queries/semantic-search/use-semantic-search";
import TagInput from "@/components/common/tagInputComponent";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface FolderCardsViewProps {
  setOpenModal: (open: boolean) => void;
  onFolderClick: (folderId: string) => void;
  onRenameFolder?: (folder: FolderType) => void;
  onDeleteFolder?: (folder: FolderType) => void;
  onFilesClick?: () => void;
}

export default function FolderCardsView({
  setOpenModal,
  onFolderClick,
  onRenameFolder,
  onDeleteFolder,
  onFilesClick,
}: FolderCardsViewProps): JSX.Element {
  const folders = useFolderStore((state) => state.folders);
  const agents = useAgentsManagerStore((state) => state.agents);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [projectTags, setProjectTags] = useState<string[]>([]);
  const [selectedTagFilter, setSelectedTagFilter] = useState<string[]>([]);
  const [expandedTableRow, setExpandedTableRow] = useState<string | null>(null);
  const [infoPopoverFolderId, setInfoPopoverFolderId] = useState<string | null>(null);
  const [copiedEmail, setCopiedEmail] = useState<string | null>(null);
  const [headerHeight, setHeaderHeight] = useState(0);
  const headerRef = useRef<HTMLDivElement>(null);
  const searchContainerRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [showSearchDropdown, setShowSearchDropdown] = useState(false);
  const [semanticEnabled, setSemanticEnabled] = useState(false);
  const [selectedDepartment, setSelectedDepartment] = useState("all");
  const [selectedCreator, setSelectedCreator] = useState("all");
  const [sortByDate, setSortByDate] = useState<"newest" | "oldest">("newest");
  const [sortByAgents, setSortByAgents] = useState<"none" | "most" | "least">("none");
  const [agentCountFilter, setAgentCountFilter] = useState("all");
  const [showFilters, setShowFilters] = useState(false);
  const [activeFilterTab, setActiveFilterTab] = useState<
    "department" | "creator" | "sort" | "agents" | "tags"
  >("department");
  
  const { mutate: mutateAddFolder, isPending } = usePostFolders();

  const displayFolders = folders || [];
  const { permissions, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  // Mirror backend ROLE_ALIASES so every role variant resolves identically.
  const ROLE_ALIASES: Record<string, string> = {
    super_admin: "super_admin",
    department_admin: "department_admin",
    business_user: "business_user",
    root: "root",
  };
  const rawNormalized = (role || "").toLowerCase().trim().replace(/\s+/g, "_");
  const normalizedRole = ROLE_ALIASES[rawNormalized] || rawNormalized;

  const showCreatedBy = normalizedRole === "department_admin" || normalizedRole === "super_admin" || normalizedRole === "root";
  const showDepartment = normalizedRole === "super_admin" || normalizedRole === "root";
  const showOrganization = normalizedRole === "root";
  const agentCountByFolder = useMemo(() => {
    const map = new Map<string, number>();
    if (!agents || agents.length === 0) return map;
    for (const agent of agents) {
      const key = agent.project_id;
      if (!key) continue;
      map.set(key, (map.get(key) || 0) + 1);
    }
    return map;
  }, [agents]);

  const agentsByFolder = useMemo(() => {
    const map = new Map<string, AgentType[]>();
    if (!agents || agents.length === 0) return map;
    for (const agent of agents) {
      const key = agent.project_id;
      if (!key) continue;
      const folderAgents = map.get(key);
      if (folderAgents) {
        folderAgents.push(agent);
      } else {
        map.set(key, [agent]);
      }
    }
    return map;
  }, [agents]);

  const getAgentCount = (folderId: string) => agentCountByFolder.get(folderId) || 0;

  // Semantic search for projects
  const { data: semanticProjectData, isLoading: isLoadingSemanticProjects, isError: isErrorSemanticProjects } = useSemanticSearch(
    semanticEnabled && searchQuery.trim()
      ? { entity_type: "projects", q: searchQuery.trim(), top_k: 30 }
      : null,
    { enabled: semanticEnabled && searchQuery.trim().length > 0 },
  );

  // Semantic search for agents (to find projects containing matched agents)
  const { data: semanticAgentData, isLoading: isLoadingSemanticAgents, isError: isErrorSemanticAgents } = useSemanticSearch(
    semanticEnabled && searchQuery.trim()
      ? { entity_type: "agents", q: searchQuery.trim(), top_k: 50 }
      : null,
    { enabled: semanticEnabled && searchQuery.trim().length > 0 },
  );

  const semanticProjectScores = useMemo(() => {
    if (!semanticEnabled || !searchQuery.trim()) return null;
    const scores = new Map<string, number>();
    for (const r of semanticProjectData?.results ?? []) scores.set(r.id, r.score);
    return scores;
  }, [semanticEnabled, searchQuery, semanticProjectData]);

  const semanticProjectIds = semanticProjectScores;

  const semanticAgentIds = useMemo(() => {
    if (!semanticEnabled || !searchQuery.trim()) return null;
    const scores = new Map<string, number>();
    for (const r of semanticAgentData?.results ?? []) scores.set(r.id, r.score);
    return scores;
  }, [semanticEnabled, searchQuery, semanticAgentData]);

  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const isSemanticLoading = semanticEnabled && !!normalizedSearchQuery && (isLoadingSemanticProjects || isLoadingSemanticAgents);
  const isSemanticError = semanticEnabled && !!normalizedSearchQuery && (isErrorSemanticProjects || isErrorSemanticAgents);

  const departmentOptions = useMemo(() => {
    const names = new Set<string>();
    for (const folder of displayFolders) {
      if (folder.department_name) names.add(folder.department_name);
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [displayFolders]);

  const creatorOptions = useMemo(() => {
    const names = new Set<string>();
    for (const folder of displayFolders) {
      if (folder.is_own_project) {
        names.add("You");
      } else if (folder.created_by_email) {
        names.add(folder.created_by_email);
      }
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [displayFolders]);

  const filteredFolders = displayFolders
    .map((folder) => {
      const folderAgents = folder.id ? agentsByFolder.get(folder.id) ?? [] : [];
      const matchedAgents =
        normalizedSearchQuery.length === 0
          ? []
          : folderAgents.filter((agent) => {
              const matchesAgentName = agent.name
                .toLowerCase()
                .includes(normalizedSearchQuery);
              const matchesAgentDescription = agent.description
                ?.toLowerCase()
                .includes(normalizedSearchQuery);
              const matchesAgentTags = agent.tags?.some((tag) =>
                tag.toLowerCase().includes(normalizedSearchQuery),
              );
              return (
                matchesAgentName ||
                matchesAgentDescription ||
                matchesAgentTags
              );
            });

      // Semantic search: match by Pinecone results instead of keyword
      // When semantic is enabled: use Pinecone IDs. When disabled: use keyword matching.
      // When semantic is loading (IDs are null): don't filter yet (show all).
      const matchesProjectSearch = semanticEnabled && normalizedSearchQuery.length > 0
        ? (semanticProjectIds ? semanticProjectIds.has(folder.id ?? "") : true)
        : normalizedSearchQuery.length === 0 ||
          folder.name.toLowerCase().includes(normalizedSearchQuery) ||
          folder.description?.toLowerCase().includes(normalizedSearchQuery) ||
          folder.tags?.some((tag) =>
            tag.toLowerCase().includes(normalizedSearchQuery),
          );
      const semanticAgentMatch = semanticEnabled && normalizedSearchQuery.length > 0 && semanticAgentIds
        ? folderAgents.some((a) => semanticAgentIds.has(a.id))
        : false;
      const matchesSearch =
        normalizedSearchQuery.length === 0 ||
        matchesProjectSearch ||
        matchedAgents.length > 0 ||
        semanticAgentMatch;

      const matchesDepartment =
        selectedDepartment === "all" ||
        (selectedDepartment === "__none__" && !folder.department_name) ||
        folder.department_name === selectedDepartment;

      const creatorLabel = folder.is_own_project ? "You" : folder.created_by_email || "";
      const matchesCreator =
        selectedCreator === "all" ||
        (selectedCreator === "__none__" && !creatorLabel) ||
        creatorLabel === selectedCreator;

      const count = getAgentCount(folder.id);
      const matchesAgentCount =
        agentCountFilter === "all" ||
        (agentCountFilter === "0" && count === 0) ||
        (agentCountFilter === "1-5" && count >= 1 && count <= 5) ||
        (agentCountFilter === "6-10" && count >= 6 && count <= 10) ||
        (agentCountFilter === "11+" && count >= 11);

      const matchesTags =
        selectedTagFilter.length === 0 ||
        selectedTagFilter.every((tag) => folder.tags?.includes(tag));

      if (
        !matchesSearch ||
        !matchesDepartment ||
        !matchesCreator ||
        !matchesAgentCount ||
        !matchesTags
      ) {
        return null;
      }

      return { folder, matchedAgents };
    })
    .filter(
      (
        item,
      ): item is {
        folder: FolderType;
        matchedAgents: AgentType[];
      } => item !== null,
    );

  // Compute best semantic score per folder: max(project score, best agent score inside it)
  const getBestSemanticScore = (folderId: string | null | undefined): number => {
    if (!folderId) return 0;
    if (!semanticEnabled || !normalizedSearchQuery) return 0;
    const projectScore = semanticProjectScores?.get(folderId) ?? 0;
    let bestAgentScore = 0;
    if (semanticAgentIds) {
      const folderAgents = agentsByFolder.get(folderId) ?? [];
      for (const agent of folderAgents) {
        const s = semanticAgentIds.get(agent.id) ?? 0;
        if (s > bestAgentScore) bestAgentScore = s;
      }
    }
    return Math.max(projectScore, bestAgentScore);
  };

  const sortedFolders = [...filteredFolders].sort((a, b) => {
    // When semantic search is active, sort by best relevance score (project or agent inside)
    if (semanticEnabled && normalizedSearchQuery && (semanticProjectScores || semanticAgentIds)) {
      const aScore = getBestSemanticScore(a.folder.id ?? "");
      const bScore = getBestSemanticScore(b.folder.id ?? "");
      if (aScore !== bScore) return bScore - aScore;
    }
    if (sortByAgents !== "none") {
      const aCount = getAgentCount(a.folder.id);
      const bCount = getAgentCount(b.folder.id);
      if (aCount !== bCount) {
        return sortByAgents === "most" ? bCount - aCount : aCount - bCount;
      }
    }
    const aDate = a.folder.updated_at || a.folder.created_at;
    const bDate = b.folder.updated_at || b.folder.created_at;
    const dateDiff = (() => {
      if (!aDate && !bDate) return 0;
      if (!aDate) return 1;
      if (!bDate) return -1;
      return new Date(aDate).getTime() - new Date(bDate).getTime();
    })();
    const dateOrder = sortByDate === "newest" ? -dateDiff : dateDiff;
    return dateOrder;
  });
  
  // Split folders into recent (top 4) and older
  const recentFolders = sortedFolders;
  const olderFolders = sortedFolders.slice(0, 0);
  const searchDropdownResults = sortedFolders.slice(0, 6);

  const formatMatchedAgentNames = (matchedAgents: AgentType[]) => {
    const visibleNames = matchedAgents.slice(0, 2).map((agent) => agent.name);
    const remainingCount = matchedAgents.length - visibleNames.length;
    return remainingCount > 0
      ? `${visibleNames.join(", ")} +${remainingCount} more`
      : visibleNames.join(", ");
  };

  // Format date
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
  };

  // Open create modal
  const handleOpenCreateModal = () => {
    setProjectName("");
    setProjectDescription("");
    setProjectTags([]);
    setCreateModalOpen(true);
  };

  useEffect(() => {
    const openModalFromEvent = () => {
      setProjectName("");
      setProjectDescription("");
      setProjectTags([]);
      setCreateModalOpen(true);
    };

    window.addEventListener("open-create-project-modal", openModalFromEvent);

    const url = new URL(window.location.href);
    if (url.searchParams.get("openCreateProject") === "1") {
      openModalFromEvent();
      url.searchParams.delete("openCreateProject");
      const nextSearch = url.searchParams.toString();
      window.history.replaceState(
        {},
        "",
        `${url.pathname}${nextSearch ? `?${nextSearch}` : ""}${url.hash}`,
      );
    }

    return () => {
      window.removeEventListener("open-create-project-modal", openModalFromEvent);
    };
  }, []);


  // Measure header height for sticky table header
  useEffect(() => {
    if (headerRef.current) {
      setHeaderHeight(headerRef.current.offsetHeight);
    }
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        searchContainerRef.current &&
        !searchContainerRef.current.contains(event.target as Node)
      ) {
        setShowSearchDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  // Handle creating new folder
  const handleCreateNewFolder = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!projectName.trim()) {
      setErrorData({ title: "Project name is required" });
      return;
    }

    mutateAddFolder(
      {
        data: {
          name: projectName.trim(),
          parent_id: null,
          description: projectDescription.trim(),
          tags: projectTags,
        },
      },
      {
        onSuccess: (folder) => {
          track("Create New Project");
          setSuccessData({
            title: "Project created successfully.",
          });
          setCreateModalOpen(false);
          setProjectName("");
          setProjectDescription("");
          setProjectTags([]);
          onFolderClick(folder.id);
        },
        onError: (err) => {
          console.error(err);
          setErrorData({ title: "Failed to create project" });
        },
      },
    );
  };


  return (
    <>
      <div className="relative flex h-full w-full flex-col overflow-auto bg-background text-foreground">
        {/* ambient command-center glows */}
        <div className="pointer-events-none fixed inset-0 overflow-hidden">
          <div className="absolute -top-24 left-1/4 h-80 w-80 rounded-full dark:bg-sky-500/20 blur-[130px]" />
          <div className="absolute top-1/3 right-0 h-80 w-80 rounded-full dark:bg-violet-500/15 blur-[130px]" />
          <div className="absolute bottom-0 left-0 h-80 w-80 rounded-full dark:bg-[#D04A02]/15 blur-[130px]" />
        </div>
        {/* Header */}
        <div ref={headerRef} className="relative z-20 flex items-center justify-between border-b border-border dark:border-white/10 bg-background dark:bg-white/[0.03] px-6 py-4 sticky top-0">
          <div className="flex items-center gap-3">
            <span className="h-9 w-1.5 rounded-full bg-[#D04A02]" style={{ boxShadow: "0 0 14px rgba(208,74,2,0.9)" }} />
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
              <p className="text-sm text-muted-foreground">
                Start a new project or select an existing one
              </p>
            </div>
          </div>
          
          <div className="flex flex-wrap items-center gap-3">
            {/* Search Bar */}
            <div ref={searchContainerRef} className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder={semanticEnabled ? "Semantic search projects & agents..." : "Search projects & agents..."}
                value={searchQuery}
                onFocus={() =>
                  normalizedSearchQuery && setShowSearchDropdown(true)
                }
                onChange={(e) => {
                  const nextValue = e.target.value;
                  setSearchQuery(nextValue);
                  setShowSearchDropdown(nextValue.trim().length > 0);
                }}
                className="h-10 w-72 rounded-lg border border-input bg-background pl-9 pr-9 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 transition-shadow"
              />
              {searchQuery && (
                <button
                  onClick={() => {
                    setSearchQuery("");
                    setShowSearchDropdown(false);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
              {showSearchDropdown && normalizedSearchQuery && (
                <div className="absolute left-0 top-full z-50 mt-2 w-96 overflow-hidden rounded-xl border bg-popover shadow-2xl animate-in fade-in-0 zoom-in-95 slide-in-from-top-2">
                  {/* Dropdown header */}
                  <div className="border-b px-4 py-2.5">
                    <p className="text-xs font-medium text-muted-foreground">
                      {isSemanticLoading
                        ? "Searching..."
                        : isSemanticError
                          ? "Search unavailable"
                          : searchDropdownResults.length > 0
                            ? `${searchDropdownResults.length} result${searchDropdownResults.length !== 1 ? "s" : ""} found`
                            : "No results"}
                    </p>
                  </div>

                  {isSemanticLoading ? (
                    <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                      <div className="flex items-center gap-1">
                        <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
                        <span className="h-2 w-2 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
                        <span className="h-2 w-2 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Searching with AI...
                      </p>
                    </div>
                  ) : isSemanticError ? (
                    <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                      <Search className="h-8 w-8 text-destructive/40" />
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">
                          Search unavailable
                        </p>
                        <p className="text-xs text-muted-foreground/70">
                          Try again or disable semantic search
                        </p>
                      </div>
                    </div>
                  ) : searchDropdownResults.length > 0 ? (
                    <div className="max-h-[360px] overflow-y-auto p-1.5">
                      {searchDropdownResults.map(({ folder, matchedAgents }, idx) => (
                        <button
                          key={folder.id}
                          type="button"
                          onClick={() => {
                            setShowSearchDropdown(false);
                            onFolderClick(folder.id);
                          }}
                          className="group flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-accent"
                        >
                          {/* Icon */}
                          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
                            <Folder className="h-4 w-4" />
                          </div>

                          {/* Content */}
                          <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate text-sm font-medium text-foreground">
                                {folder.name}
                              </span>
                              <span className="shrink-0 text-[11px] text-muted-foreground">
                                {getAgentCount(folder.id)} agent{getAgentCount(folder.id) !== 1 ? "s" : ""}
                              </span>
                            </div>

                            {folder.description && (
                              <p className="truncate text-xs text-muted-foreground">
                                {folder.description}
                              </p>
                            )}

                            {matchedAgents.length > 0 && (
                              <div
                                className="flex items-center gap-1.5 text-xs text-primary"
                                title={matchedAgents
                                  .map((agent) => agent.name)
                                  .join(", ")}
                              >
                                <Bot className="h-3 w-3 shrink-0" />
                                <span className="truncate">
                                  {formatMatchedAgentNames(matchedAgents)}
                                </span>
                              </div>
                            )}

                            {folder.tags && folder.tags.length > 0 && (
                              <div className="flex items-center gap-1 overflow-hidden">
                                <Tag className="h-3 w-3 shrink-0 text-muted-foreground" />
                                {folder.tags.slice(0, 3).map((tag) => (
                                  <span
                                    key={tag}
                                    className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground"
                                  >
                                    {tag}
                                  </span>
                                ))}
                                {folder.tags.length > 3 && (
                                  <span className="text-[10px] text-muted-foreground">
                                    +{folder.tags.length - 3}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                      <Search className="h-8 w-8 text-muted-foreground/40" />
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">
                          No matching projects or agents
                        </p>
                        <p className="text-xs text-muted-foreground/70">
                          Try a different search term
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <SemanticSearchToggle
              enabled={semanticEnabled}
              onToggle={setSemanticEnabled}
              isSearching={(isLoadingSemanticProjects || isLoadingSemanticAgents) && semanticEnabled && !!searchQuery.trim()}
            />

            <Button
              variant="outline"
              onClick={() => {
                setShowFilters(true);
                if (showDepartment) setActiveFilterTab("department");
                else if (showCreatedBy) setActiveFilterTab("creator");
                else setActiveFilterTab("sort");
              }}
            >
              Filters
            </Button>

            {onFilesClick && (
              <Button
                onClick={onFilesClick}
                variant="outline"
                className="gap-2"
              >
                <FileText className="h-4 w-4" />
                My Files
              </Button>
            )}
          </div>
        </div>

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
                      onClick={() => {
                        setSelectedDepartment("all");
                        setSelectedCreator("all");
                        setSortByDate("newest");
                        setSortByAgents("none");
                        setAgentCountFilter("all");
                        setSelectedTagFilter([]);
                      }}
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
                  <div className="w-40 border-r bg-muted/40 p-3 text-sm">
                    <div className="flex flex-col gap-1">
                      {showDepartment && (
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
                      )}
                      {showCreatedBy && (
                        <button
                          onClick={() => setActiveFilterTab("creator")}
                          className={`rounded-md px-3 py-2 text-left ${
                            activeFilterTab === "creator"
                              ? "bg-background font-semibold shadow-sm"
                              : "text-muted-foreground"
                          }`}
                        >
                          Created By
                        </button>
                      )}
                      <button
                        onClick={() => setActiveFilterTab("sort")}
                        className={`rounded-md px-3 py-2 text-left ${
                          activeFilterTab === "sort"
                            ? "bg-background font-semibold shadow-sm"
                            : "text-muted-foreground"
                        }`}
                      >
                        Sort
                      </button>
                      <button
                        onClick={() => setActiveFilterTab("agents")}
                        className={`rounded-md px-3 py-2 text-left ${
                          activeFilterTab === "agents"
                            ? "bg-background font-semibold shadow-sm"
                            : "text-muted-foreground"
                        }`}
                      >
                        Agents
                      </button>
                      <button
                        onClick={() => setActiveFilterTab("tags")}
                        className={`rounded-md px-3 py-2 text-left ${
                          activeFilterTab === "tags"
                            ? "bg-background font-semibold shadow-sm"
                            : "text-muted-foreground"
                        }`}
                      >
                        Tags
                        {selectedTagFilter.length > 0 && (
                          <Badge variant="default" size="sm" className="ml-1.5">
                            {selectedTagFilter.length}
                          </Badge>
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="flex-1 overflow-auto p-5">
                    {activeFilterTab === "department" && showDepartment && (
                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Department</h3>
                        <select
                          value={selectedDepartment}
                          onChange={(e) => setSelectedDepartment(e.target.value)}
                          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                        >
                          <option value="all">All departments</option>
                          <option value="__none__">No department scope</option>
                          {departmentOptions.map((dept) => (
                            <option key={dept} value={dept}>
                              {dept}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                    {activeFilterTab === "creator" && showCreatedBy && (
                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Created By</h3>
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

                    {activeFilterTab === "sort" && (
                      <div className="space-y-6">
                        <div className="space-y-3">
                          <h3 className="text-sm font-semibold">Sort by date</h3>
                          <select
                            value={sortByDate}
                            onChange={(e) => setSortByDate(e.target.value as "newest" | "oldest")}
                            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                          >
                            <option value="newest">Newest first</option>
                            <option value="oldest">Oldest first</option>
                          </select>
                        </div>
                        <div className="space-y-3">
                          <h3 className="text-sm font-semibold">Sort by agents</h3>
                          <select
                            value={sortByAgents}
                            onChange={(e) => setSortByAgents(e.target.value as "none" | "most" | "least")}
                            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                          >
                            <option value="none">No agent sort</option>
                            <option value="most">Most agents</option>
                            <option value="least">Least agents</option>
                          </select>
                        </div>
                      </div>
                    )}

                    {activeFilterTab === "agents" && (
                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Agent count</h3>
                        <select
                          value={agentCountFilter}
                          onChange={(e) => setAgentCountFilter(e.target.value)}
                          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                        >
                          <option value="all">Any agent count</option>
                          <option value="0">0 agents</option>
                          <option value="1-5">1-5 agents</option>
                          <option value="6-10">6-10 agents</option>
                          <option value="11+">11+ agents</option>
                        </select>
                      </div>
                    )}

                    {activeFilterTab === "tags" && (
                      <div className="space-y-3">
                        <h3 className="text-sm font-semibold">Filter by Tags</h3>
                        <p className="text-xs text-muted-foreground">
                          Select tags to filter projects. Only projects with all selected tags will be shown.
                        </p>
                        <TagInput
                          selectedTags={selectedTagFilter}
                          onChange={setSelectedTagFilter}
                          placeholder="Search and select tags..."
                        />
                        {selectedTagFilter.length > 0 && (
                          <button
                            onClick={() => setSelectedTagFilter([])}
                            className="text-xs text-primary hover:underline"
                          >
                            Clear tag filter
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-between border-t bg-background px-5 py-4">
                  <span className="text-xs text-muted-foreground">
                    {filteredFolders.length} projects found
                  </span>
                  <Button onClick={() => setShowFilters(false)}>Apply</Button>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Cards Section - All Projects */}
        <div className="px-6 py-5">
          <h2 className="mb-4 text-sm font-semibold text-muted-foreground">
            All Projects
            <span className="ml-1.5 font-normal text-muted-foreground/60">({filteredFolders.length})</span>
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">

            {/* Create New Project Card*/}
            {can("view_projects_page") && (
            <div
              onClick={!isPending ? handleOpenCreateModal : undefined}
              className="group relative flex min-h-[150px] cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-border dark:border-white/15 bg-transparent dark:bg-white/[0.02] p-4 transition-all duration-300 hover:-translate-y-1 hover:border-[#D04A02]/60"
            >
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-xl bg-[#D04A02]/15 transition-colors group-hover:bg-[#D04A02]/25${isPending ? " opacity-50" : ""}`}
              >
                <Plus className="h-6 w-6 text-[#D04A02]" />
              </div>
              <span className="text-center text-xs font-semibold text-muted-foreground">Blank project</span>
            </div>
            )}

            {/* Recent Folder Cards*/}
            {recentFolders.map(({ folder, matchedAgents }) => {
              const agentCount = getAgentCount(folder.id);
              const isPopoverOpen = infoPopoverFolderId === folder.id;
              return (
                <div
                  key={folder.id}
                  className="group relative flex flex-col rounded-2xl border border-border dark:border-white/10 bg-card dark:bg-white/[0.04] p-4 transition-all duration-300 hover:-translate-y-1"
                  style={{ boxShadow: "0 0 0 1px rgba(255,255,255,0.05), 0 16px 50px -24px rgba(208,74,2,0.45)" }}
                >
                  {/* Header: icon + name + actions */}
                  <div className="flex items-start gap-3">
                    <button
                      type="button"
                      onClick={() => can("view_projects_page") && onFolderClick(folder.id)}
                      disabled={!can("view_projects_page")}
                      aria-label={folder.name}
                      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 transition-colors group-hover:bg-primary/15 disabled:cursor-not-allowed"
                    >
                      <Folder className="h-5 w-5 text-primary" />
                    </button>
                    <button
                      type="button"
                      onClick={() => can("view_projects_page") && onFolderClick(folder.id)}
                      disabled={!can("view_projects_page")}
                      className="min-w-0 flex-1 pt-0.5 text-left disabled:cursor-not-allowed"
                    >
                      <p className="truncate text-sm font-semibold leading-tight text-foreground">
                        {folder.name}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {agentCount} {agentCount === 1 ? "agent" : "agents"}
                      </p>
                    </button>
                    <div className="flex shrink-0 items-center gap-0.5">
                      {can("view_projects_page") && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setInfoPopoverFolderId(isPopoverOpen ? null : folder.id);
                        }}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-all hover:bg-muted hover:text-foreground group-hover:opacity-100"
                        title="View details"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                      )}
                      {(can("edit_project") || can("delete_project")) && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            onClick={(e) => e.stopPropagation()}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          >
                            <MoreVertical className="h-3.5 w-3.5" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {can("edit_project") && (
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              onRenameFolder?.(folder);
                            }}
                          >
                            <Edit2 className="mr-2 h-4 w-4" />
                            Edit
                          </DropdownMenuItem>
                          )}
                          {can("delete_project") && (
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteFolder?.(folder);
                            }}
                            className="text-destructive"
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                      )}
                    </div>
                  </div>

                  {/* Content */}
                  <div className="mt-3 flex flex-1 flex-col gap-2">
                    {folder.description?.trim() && (
                      <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground" title={folder.description}>
                        {folder.description}
                      </p>
                    )}

                  {/* Tags */}
                  {folder.tags && folder.tags.length > 0 && (
                    <div
                      className="relative flex flex-wrap justify-start gap-1 mb-1 group/tags"
                      title={folder.tags.join(", ")}
                    >
                      {folder.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="outline" size="sm" className="text-[10px] px-1.5 py-0">
                          {tag}
                        </Badge>
                      ))}
                      {folder.tags.length > 3 && (
                        <Badge variant="outline" size="sm" className="text-[10px] px-1.5 py-0 cursor-default">
                          +{folder.tags.length - 3}
                        </Badge>
                      )}
                      {/* Full tags tooltip on hover */}
                      {folder.tags.length > 3 && (
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover/tags:flex flex-wrap gap-1 bg-popover border rounded-lg p-2 shadow-lg z-50 w-max max-w-[250px]">
                          {folder.tags.map((tag) => (
                            <Badge key={tag} variant="outline" size="sm" className="text-[10px] px-1.5 py-0">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {normalizedSearchQuery && matchedAgents.length > 0 && (
                    <div
                      className="mb-2 w-full rounded-md border border-primary/20 bg-primary/5 px-2 py-1.5 text-left"
                      title={matchedAgents.map((agent) => agent.name).join(", ")}
                    >
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Matched agents
                      </p>
                      <p className="text-xs font-medium text-foreground line-clamp-2">
                        {formatMatchedAgentNames(matchedAgents)}
                      </p>
                    </div>
                  )}

                    {/* Created by + Agent count */}
                    <div className="mt-auto flex items-center gap-2 border-t border-border/50 pt-2.5 text-xs text-muted-foreground">
                      {showCreatedBy && (folder.created_by_email || folder.is_own_project) && (
                        <>
                          <span className="max-w-[55%] truncate" title={folder.created_by_email || ""}>
                            {folder.is_own_project ? (
                              <span className="font-medium text-primary">You</span>
                            ) : (
                              folder.created_by_email?.split("@")[0]
                            )}
                          </span>
                          <span className="text-border">·</span>
                        </>
                      )}
                      <span>{agentCount} {agentCount === 1 ? "agent" : "agents"}</span>
                    </div>
                  </div>

                  {/* Info Popover - shown on (i) click */}
                  {isPopoverOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-30"
                        onClick={() => setInfoPopoverFolderId(null)}
                      />
                      <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1 z-40 w-64 rounded-lg border bg-card p-3 shadow-lg">
                        <div className="space-y-2 text-xs">
                          {/* Description - trimmed, full on hover */}
                          <div>
                            <span className="font-semibold text-muted-foreground">Description</span>
                            <p
                              className="text-muted-foreground leading-relaxed mt-0.5 line-clamp-2 hover:line-clamp-none cursor-default transition-all"
                              title={folder.description || "No description"}
                            >
                              {folder.description || "No description"}
                            </p>
                          </div>

                          {/* Agents & Updated */}
                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <span className="font-semibold text-muted-foreground">Agents</span>
                              <p className="font-medium">{agentCount}</p>
                            </div>
                            {folder.updated_at && (
                              <div>
                                <span className="font-semibold text-muted-foreground">Updated</span>
                                <p className="font-medium">{formatDate(folder.updated_at)}</p>
                              </div>
                            )}
                          </div>

                          {/* Created by & Department side by side */}
                          <div className="grid grid-cols-2 gap-2">
                            {showCreatedBy && (folder.created_by_email || folder.is_own_project) && (
                              <div>
                                <span className="font-semibold text-muted-foreground">Created by</span>
                                <div className="flex items-center gap-1">
                                  <p className="font-medium truncate" title={folder.created_by_email || ""}>
                                    {folder.is_own_project ? (
                                      <span className="text-primary">You</span>
                                    ) : (
                                      folder.created_by_email?.split("@")[0]
                                    )}
                                  </p>
                                  {folder.created_by_email && (
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        navigator.clipboard.writeText(folder.created_by_email!);
                                        setCopiedEmail(folder.created_by_email!);
                                        setTimeout(() => setCopiedEmail(null), 1500);
                                      }}
                                      className="flex-shrink-0 p-0.5 rounded hover:bg-accent transition-colors"
                                      title="Copy email"
                                    >
                                      {copiedEmail === folder.created_by_email ? (
                                        <Check className="h-3 w-3 text-green-500" />
                                      ) : (
                                        <Copy className="h-3 w-3 text-muted-foreground" />
                                      )}
                                    </button>
                                  )}
                                </div>
                              </div>
                            )}
                            {showDepartment && folder.department_name && (
                              <div>
                                <span className="font-semibold text-muted-foreground">Department</span>
                                <p className="font-medium truncate">{folder.department_name}</p>
                              </div>
                            )}
                          </div>

                          {showOrganization && folder.organization_name && (
                            <div>
                              <span className="font-semibold text-muted-foreground">Organization</span>
                              <p className="font-medium">{folder.organization_name}</p>
                            </div>
                          )}
                          {folder.tags && folder.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {folder.tags.map((tag) => (
                                <Badge key={tag} variant="outline" size="sm" className="text-[10px] px-1.5 py-0">
                                  {tag}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Table/List Section - Older Projects */}
        {olderFolders.length > 0 && (
          <div className="px-6 py-4">
            <h2 className="mb-4 text-sm font-semibold text-muted-foreground">Earlier</h2>
            
            <div className="rounded-lg border bg-card">
              {/* Table Header */}
              <div
                className="flex gap-4 border-b bg-background px-4 py-3 text-xs font-semibold text-muted-foreground sticky z-10 shadow-sm items-center w-full"
                style={{ top: headerHeight ? `${headerHeight}px` : '0px' }}
              >
                <div className="flex items-center gap-2 flex-[2] min-w-0">
                  <Folder className="h-4 w-4 flex-shrink-0" />
                  <span>Name</span>
                </div>
                {showCreatedBy && <div className="flex items-center flex-1 min-w-0">Created By</div>}
                {showDepartment && <div className="flex items-center flex-1 min-w-0">Department</div>}
                {showOrganization && <div className="flex items-center flex-1 min-w-0">Organization</div>}
                <div className="flex items-center flex-1 min-w-0">Last Updated</div>
                <div className="flex items-center flex-[1.5] min-w-0">Tags</div>
                <div className="flex items-center flex-1 min-w-0">Description</div>
                <div className="w-[40px] flex-shrink-0"></div>
              </div>

              {/* Table Body */}
              <div className="divide-y">
                {olderFolders.map(({ folder, matchedAgents }) => {
                  const agentCount = getAgentCount(folder.id);
                  const isExpanded = expandedTableRow === folder.id;
                  
                  return (
                    <div key={folder.id}>
                      {/* Main Row */}
                      <div
                        className={`group flex gap-4 px-4 py-3 transition-colors hover:bg-muted/50 items-center w-full ${can("view_projects_page") ? "cursor-pointer" : "cursor-not-allowed opacity-50"}`}
                        onClick={() => can("view_projects_page") && onFolderClick(folder.id)}
                      >
                        {/* Name Column */}
                        <div className="flex items-center gap-3 flex-[2] min-w-0">
                          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded bg-primary/10">
                            <Folder className="h-4 w-4 text-primary" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium text-sm">
                              {folder.name}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                              {agentCount} {agentCount === 1 ? "agent" : "agents"}
                            </p>
                            {normalizedSearchQuery && matchedAgents.length > 0 && (
                              <p
                                className="mt-1 truncate text-xs font-medium text-primary"
                                title={matchedAgents.map((agent) => agent.name).join(", ")}
                              >
                                Matched: {formatMatchedAgentNames(matchedAgents)}
                              </p>
                            )}
                          </div>
                        </div>

                        {showCreatedBy && (
                          <div className="flex items-center flex-1 min-w-0 text-sm text-muted-foreground">
                            {folder.is_own_project ? (
                              <span className="truncate font-semibold text-primary">You</span>
                            ) : folder.created_by_email ? (
                              <span
                                className="truncate cursor-pointer hover:text-foreground transition-colors"
                                title={folder.created_by_email}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigator.clipboard.writeText(folder.created_by_email!);
                                }}
                              >
                                {folder.created_by_email.split("@")[0]}
                              </span>
                            ) : (
                              <span>--</span>
                            )}
                          </div>
                        )}
                        {showDepartment && (
                          <div className="flex items-center flex-1 min-w-0 text-sm text-muted-foreground">
                            <span className="truncate">{folder.department_name || "--"}</span>
                          </div>
                        )}
                        {showOrganization && (
                          <div className="flex items-center flex-1 min-w-0 text-sm text-muted-foreground">
                            <span className="truncate">{folder.organization_name || "--"}</span>
                          </div>
                        )}
                        <div className="flex items-center flex-1 min-w-0 text-sm text-muted-foreground">
                          {folder.updated_at || folder.created_at ? (
                            <span className="truncate">{formatDate(folder.updated_at || folder.created_at!)}</span>
                          ) : (
                            <span className="truncate">--</span>
                          )}
                        </div>

                        {/* Tags Column */}
                        <div className="relative flex items-center flex-[1.5] min-w-0 group/tagtable">
                          {folder.tags && folder.tags.length > 0 ? (
                            <div
                              className="flex flex-wrap gap-1"
                              title={folder.tags.join(", ")}
                            >
                              {folder.tags.slice(0, 4).map((tag) => (
                                <Badge key={tag} variant="outline" size="sm" className="text-[10px] px-1.5 py-0">
                                  {tag}
                                </Badge>
                              ))}
                              {folder.tags.length > 4 && (
                                <Badge variant="outline" size="sm" className="text-[10px] px-1.5 py-0 cursor-default">
                                  +{folder.tags.length - 4}
                                </Badge>
                              )}
                              {/* Full tags tooltip on hover */}
                              {folder.tags.length > 4 && (
                                <div className="absolute bottom-full left-0 mb-1 hidden group-hover/tagtable:flex flex-wrap gap-1 bg-popover border rounded-lg p-2 shadow-lg z-50 w-max max-w-[300px]">
                                  {folder.tags.map((tag) => (
                                    <Badge key={tag} variant="outline" size="sm" className="text-[10px] px-1.5 py-0">
                                      {tag}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-sm text-muted-foreground">--</span>
                          )}
                        </div>

                        {/* Description Column */}
                        <div className="relative flex items-center flex-1 min-w-0 group/desc">
                          {folder.description ? (
                            <>
                              <p className="text-xs text-muted-foreground truncate cursor-default">
                                {folder.description}
                              </p>
                              <div className="absolute bottom-full right-0 mb-1 hidden group-hover/desc:block bg-popover border rounded-lg p-3 shadow-lg z-50 w-max max-w-[300px]">
                                <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap">
                                  {folder.description}
                                </p>
                              </div>
                            </>
                          ) : (
                            <span className="text-sm text-muted-foreground">--</span>
                          )}
                        </div>

                        {/* Actions Column */}
                        <div className="w-[40px] flex-shrink-0 flex items-center justify-end">
                          {(can("edit_project") || can("delete_project")) && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                onClick={(e) => e.stopPropagation()}
                                className="flex h-8 w-8 items-center justify-center rounded-md transition-opacity hover:bg-accent"
                              >
                                <MoreVertical className="h-4 w-4" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {can("edit_project") && (
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onRenameFolder?.(folder);
                                }}
                              >
                                <Edit2 className="mr-2 h-4 w-4" />
                                Edit
                              </DropdownMenuItem>
                              )}
                              {can("delete_project") && (
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onDeleteFolder?.(folder);
                                }}
                                className="text-destructive"
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                Delete
                              </DropdownMenuItem>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                          )}
                        </div>
                      </div>

                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Empty State */}
        {filteredFolders.length === 0 && (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-lg bg-primary/10">
                <Folder className="h-8 w-8 text-primary" />
              </div>
              {searchQuery ? (
                <>
                  <h3 className="mb-2 text-lg font-semibold">No projects found</h3>
                  <p className="mb-4 text-sm text-muted-foreground">
                    No projects match "{searchQuery}"
                  </p>
                  <button
                    onClick={() => setSearchQuery("")}
                    className="text-sm text-primary hover:underline"
                  >
                    Clear search
                  </button>
                </>
              ) : (
                <>
                  <h3 className="mb-2 text-lg font-semibold">No projects yet</h3>
                  <p className="mb-4 text-sm text-muted-foreground">
                    Create your first project to get started
                  </p>
                  <button
                    onClick={handleOpenCreateModal}
                    disabled={isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-[var(--button-primary)] px-4 py-2 text-sm font-medium text-[var(--button-primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" />
                    Create Project
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {createModalOpen && (
        <>
          <div
            className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
            onClick={() => setCreateModalOpen(false)}
          />

          <div className="fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-lg border border-border bg-card p-6 shadow-lg">
            <div className="mb-6 flex items-start justify-between">
              <div>
                <h2 className="text-xl font-semibold">
                  Create New Project
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Enter a name and description for your project
                </p>
              </div>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
              >
                <X className="h-5 w-5" />
                <span className="sr-only">Close</span>
              </button>
            </div>

            <form onSubmit={handleCreateNewFolder} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="projectName" className="text-sm font-medium">
                  Project Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="projectName"
                  required
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g., Customer Support Workagent"
                  className="bg-background"
                  autoFocus
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="projectDescription" className="text-sm font-medium">
                  Description (Optional)
                </Label>
                <Textarea
                  id="projectDescription"
                  value={projectDescription}
                  onChange={(e) => setProjectDescription(e.target.value)}
                  placeholder="Brief description of your project..."
                  rows={3}
                  className="resize-none bg-background"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-sm font-medium">
                  Tags (Optional)
                </Label>
                <TagInput
                  selectedTags={projectTags}
                  onChange={setProjectTags}
                  placeholder="Add tags (e.g. rag, chatbot, finance)..."
                  maxTags={10}
                />
              </div>

              <div className="flex items-center gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setCreateModalOpen(false)}
                  className="flex-1"
                  disabled={isPending}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="default"
                  className="flex-1"
                  disabled={isPending}
                >
                  {isPending ? "Creating..." : "Create Project"}
                </Button>
              </div>
            </form>
          </div>
        </>
      )}

      {/* Project Details Modal - ENTERPRISE DESIGN */}
    </>
  );
}
