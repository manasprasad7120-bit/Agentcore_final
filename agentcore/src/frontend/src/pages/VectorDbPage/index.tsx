import {
  Search,
  Activity,
  ArrowRight,
  CheckCircle,
  Clock,
  XCircle,
  Database,
  Trash2,
} from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Loading from "@/components/ui/loading";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useGetVectorDBCatalogue,
  type VectorDBInfo,
} from "@/controllers/API/queries/vector-db/use-get-vector-db-catalogue";
import { useDeleteVectorDBCatalogue } from "@/controllers/API/queries/vector-db/use-delete-vector-db-catalogue";
import { getProviderIcon } from "@/utils/logo_provider";
import { AuthContext } from "@/contexts/authContext";

type EnvFilter = "all" | "uat" | "prod";

const ENV_LABELS: Record<string, string> = {
  all: "All Envs",
  uat: "UAT",
  prod: "PROD",
};

const ENV_BADGE_CLASSES: Record<string, string> = {
  uat: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  prod: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
};

const MIGRATION_BADGE: Record<string, { cls: string; icon: typeof CheckCircle }> = {
  completed: { cls: "text-green-600", icon: CheckCircle },
  pending: { cls: "text-yellow-600", icon: Clock },
  failed: { cls: "text-red-600", icon: XCircle },
};

export default function VectorDBView(): JSX.Element {
  const { t } = useTranslation();
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const { permissions } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canDelete = can("delete_vector_db_catalogue");

  // Always fetch all entries so stats reflect the full picture
  const {
    data: dbVectorDBs,
    isLoading,
    error,
  } = useGetVectorDBCatalogue({ environment: "all" });

  const deleteMutation = useDeleteVectorDBCatalogue();
  const [deletingId, setDeletingId] = useState<string | null>(null);

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
      ro.disconnect();
      scroll.removeEventListener("scroll", onScrollContent);
      mirror.removeEventListener("scroll", onScrollMirror);
    };
  }, []);

  const handleDelete = (db: VectorDBInfo) => {
    if (!window.confirm(`Delete "${db.name}" from the catalogue?`)) return;
    setDeletingId(db.id);
    deleteMutation.mutate(
      { id: db.id },
      { onSettled: () => setDeletingId(null) },
    );
  };

  const displayVectorDBs: VectorDBInfo[] = dbVectorDBs ?? [];

  /* ---------------------------------- Stats ---------------------------------- */

  const stats = useMemo(() => {
    const all = dbVectorDBs ?? [];
    return {
      total: all.length,
      uat: all.filter((d) => d.environment === "uat").length,
      prod: all.filter((d) => d.environment === "prod").length,
      migrated: all.filter((d) => d.migrationStatus === "completed").length,
    };
  }, [dbVectorDBs]);

  /* ---------------------------------- Filtering ---------------------------------- */

  const filteredVectorDBs = displayVectorDBs.filter((db) => {
    const matchesEnv =
      envFilter === "all" || db.environment === envFilter;
    if (!matchesEnv) return false;

    const matchesSearch =
      !searchQuery ||
      db.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.provider.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.indexName?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.namespace?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.agentName?.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesSearch;
  });

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

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      connected: "bg-green-500",
      disconnected: "bg-red-500",
      configuring: "bg-yellow-500",
      error: "bg-red-500",
    };
    return colors[status] || "bg-gray-400";
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      connected: "Connected",
      disconnected: "Disconnected",
      configuring: "Configuring",
      error: "Error",
    };
    return t(labels[status] || status);
  };

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 flex flex-col gap-4 border-b px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-xl font-semibold md:text-2xl">{t("Vector DB Catalogue")}</h1>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search by name, index, namespace, agent...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring sm:w-80"
            />
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="flex-shrink-0 border-b px-4 py-4 sm:px-6 md:px-8">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div className="rounded-lg border bg-card p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Database className="h-4 w-4" />
              {t("Total Namespaces")}
            </div>
            <div className="mt-1 text-2xl font-semibold">{stats.total}</div>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <div className="flex items-center gap-2 text-sm text-blue-600">
              <Activity className="h-4 w-4" />
              {t("UAT Active")}
            </div>
            <div className="mt-1 text-2xl font-semibold">{stats.uat}</div>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <div className="flex items-center gap-2 text-sm text-green-600">
              <CheckCircle className="h-4 w-4" />
              {t("PROD Active")}
            </div>
            <div className="mt-1 text-2xl font-semibold">{stats.prod}</div>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <ArrowRight className="h-4 w-4" />
              {t("Promoted to PROD")}
            </div>
            <div className="mt-1 text-2xl font-semibold">{stats.migrated}</div>
          </div>
        </div>
      </div>

      {/* Table */}
      <style>{`
        .vdb-table-scroll::-webkit-scrollbar { height: 0; }
        .vdb-table-scroll { scrollbar-width: none; }
        .vdb-mirror-bar::-webkit-scrollbar { height: 8px; }
        .vdb-mirror-bar::-webkit-scrollbar-track { background: hsl(var(--muted)); border-radius: 9999px; }
        .vdb-mirror-bar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground)); border-radius: 9999px; }
        .vdb-mirror-bar::-webkit-scrollbar-thumb:hover { background: hsl(var(--foreground) / 0.8); }
        .vdb-mirror-bar { scrollbar-width: thin; scrollbar-color: hsl(var(--muted-foreground)) hsl(var(--muted)); }
      `}</style>
      <div className="flex-1 flex flex-col overflow-hidden p-4 sm:p-6 gap-3">
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border bg-card">
          <div ref={tableScrollRef} className="vdb-table-scroll flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        ) : (
          <>
            {!!error && (
              <div className="mx-4 mt-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {t("Failed to load vector databases from database.")}
              </div>
            )}
              <table className="w-full min-w-[900px]">
                <thead className="sticky top-0 z-10 bg-card shadow-sm">
                  <tr className="border-b border-border">
                    {[
                      "Name",
                      "Environment",
                      "Index / Namespace",
                      "Agent",
                      "Status",
                      "Records",
                      "Migration",
                      ...(canDelete ? [""] : []),
                    ].map((h, i) => (
                      <th
                        key={h || `col-${i}`}
                        className="px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                      >
                        {h ? t(h) : ""}
                      </th>
                    ))}
                  </tr>
                </thead>

                <tbody className="divide-y divide-border">
                  {filteredVectorDBs.length === 0 ? (
                    <tr>
                      <td
                        colSpan={canDelete ? 8 : 7}
                        className="px-4 py-12 text-center text-muted-foreground"
                      >
                        {displayVectorDBs.length === 0
                          ? t("No vector databases tracked yet. Entries appear automatically when agents with vector stores are deployed or promoted to PROD.")
                          : t("No entries match your current filters.")}
                      </td>
                    </tr>
                  ) : (
                    filteredVectorDBs.map((db) => {
                      const migBadge = MIGRATION_BADGE[db.migrationStatus] ?? null;
                      const MigIcon = migBadge?.icon;

                      return (
                        <tr key={db.id} className="group hover:bg-muted/50">
                          {/* Name */}
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-2">
                              <div className="flex h-8 w-8 items-center justify-center rounded border">
                                {getProviderLogo(db.provider)}
                              </div>
                              <div>
                                <div
                                  className="max-w-[240px] line-clamp-2 font-semibold leading-6"
                                  title={db.name}
                                >
                                  {db.name}
                                </div>
                                {db.description && (
                                  <div
                                    className="mt-0.5 max-w-[240px] truncate text-xs text-muted-foreground"
                                    title={db.description}
                                  >
                                    {db.description}
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* Environment */}
                          <td className="px-4 py-4">
                            <span
                              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium uppercase ${
                                ENV_BADGE_CLASSES[db.environment] ??
                                "bg-gray-100 text-gray-700"
                              }`}
                            >
                              {t(ENV_LABELS[db.environment] ?? db.environment)}
                            </span>
                          </td>

                          {/* Index / Namespace */}
                          <td className="px-4 py-4">
                            {db.indexName ? (
                              <div>
                                <div
                                  className="max-w-[220px] truncate font-mono text-sm"
                                  title={db.indexName}
                                >
                                  {db.indexName}
                                </div>
                                <div
                                  className="mt-0.5 max-w-[220px] truncate font-mono text-xs text-muted-foreground"
                                  title={db.namespace || "(default)"}
                                >
                                  ns: {db.namespace || "(default)"}
                                </div>
                              </div>
                            ) : (
                              <span className="text-sm text-muted-foreground">-</span>
                            )}
                          </td>

                          {/* Agent */}
                          <td className="px-4 py-4">
                            {db.agentName ? (
                              <div className="max-w-[150px] truncate text-sm" title={db.agentName}>
                                {db.agentName}
                              </div>
                            ) : (
                              <span className="text-sm text-muted-foreground">-</span>
                            )}
                          </td>

                          {/* Status */}
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-2">
                              <span
                                className={`h-2 w-2 rounded-full ${getStatusColor(db.status)}`}
                              ></span>
                              <span className="text-sm">
                                {getStatusLabel(db.status)}
                              </span>
                            </div>
                          </td>

                          {/* Vectors */}
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-1">
                              <Activity className="h-3 w-3 text-muted-foreground" />
                              <span className="text-sm font-medium">
                                {db.environment === "prod" && db.vectorsCopied > 0
                                  ? db.vectorsCopied.toLocaleString()
                                  : Number(db.vectorCount || 0).toLocaleString()}
                              </span>
                            </div>
                          </td>

                          {/* Migration */}
                          <td className="px-4 py-4">
                            {db.environment === "prod" && migBadge && MigIcon ? (
                              <div>
                                <span className={`inline-flex items-center gap-1 text-xs font-medium ${migBadge.cls}`}>
                                  <MigIcon className="h-3.5 w-3.5" />
                                  {t(db.migrationStatus.charAt(0).toUpperCase() + db.migrationStatus.slice(1))}
                                </span>
                                {db.migratedAt && (
                                  <div className="mt-0.5 text-xxs text-muted-foreground">
                                    {new Date(db.migratedAt).toLocaleDateString()}
                                  </div>
                                )}
                              </div>
                            ) : db.environment === "uat" ? (
                              <span className="text-xs text-muted-foreground">{t("Source")}</span>
                            ) : (
                              <span className="text-xs text-muted-foreground">-</span>
                            )}
                          </td>

                          {/* Delete */}
                          {canDelete && (
                            <td className="px-4 py-4">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                                disabled={deletingId === db.id}
                                onClick={() => handleDelete(db)}
                                title={t("Delete entry")}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </td>
                          )}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
          </>
        )}
          </div>
          <div ref={mirrorRef} className="vdb-mirror-bar flex-shrink-0 overflow-x-scroll overflow-y-hidden border-t" style={{ height: 12 }}>
            <div ref={phantomRef} style={{ height: 1 }} />
          </div>
        </div>
        <div className="text-center text-sm text-muted-foreground flex-shrink-0">
          {t("Showing {{shown}} of {{total}} vector databases", {
            shown: filteredVectorDBs.length,
            total: displayVectorDBs.length,
          })}
        </div>
      </div>
    </div>
  );
}
