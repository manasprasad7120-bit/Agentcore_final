import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Globe } from "lucide-react";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import {
  type ReleaseRecord,
  useGetCurrentRelease,
  useGetReleaseDocumentPreview,
  useGetReleasePackageComparison,
  useGetReleases,
  usePostBumpReleaseWithDocument,
} from "@/controllers/API/queries/releases";
import { AuthContext } from "@/contexts/authContext";
import useAlertStore from "@/stores/alertStore";
import useRegionStore from "@/stores/regionStore";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Loading from "@/components/ui/loading";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

const ACTIVE_END_DATE = "9999-12-31";

type BumpType = "major" | "minor" | "patch";
type PackageViewTab = "managed" | "transitive";

const BUMP_OPTIONS: { value: BumpType; label: string; description: string }[] = [
  { value: "major", label: "Major", description: "Breaking release" },
  { value: "minor", label: "Minor", description: "Feature release" },
  { value: "patch", label: "Patch", description: "Fix release" },
];

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString();
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

function formatFileSize(size?: number | null) {
  if (!size || size <= 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatComparisonStatus(status: string) {
  if (status === "unchanged") return "Unchanged";
  if (status === "upgraded") return "Upgraded";
  if (status === "downgraded") return "Downgraded";
  if (status === "new") return "New";
  if (status === "removed") return "Removed";
  return "Changed";
}

function comparisonStatusClass(status: string) {
  if (status === "unchanged") return "border-slate-300 text-slate-600";
  if (status === "upgraded") return "border-green-500/50 text-green-600";
  if (status === "downgraded") return "border-amber-500/50 text-amber-600";
  if (status === "new") return "border-blue-500/50 text-blue-600";
  if (status === "removed") return "border-red-500/50 text-red-600";
  return "border-violet-500/50 text-violet-600";
}

function ReleaseLibrariesTab({
  releaseId,
  regionCode,
}: {
  releaseId: string;
  regionCode?: string | null;
}) {
  const { t } = useTranslation();
  const [selectedService, setSelectedService] = useState("all");
  const [activeTab, setActiveTab] = useState<PackageViewTab>("managed");
  const [searchQuery, setSearchQuery] = useState("");
  const [showChangedOnly, setShowChangedOnly] = useState(false);
  const { data: comparisonData, isLoading } = useGetReleasePackageComparison(
    { releaseId, service: selectedService, regionCode },
  );

  const normalizedData = useMemo(
    () =>
      (comparisonData ?? []).map((row) => ({
        ...row,
        service_name: row.service_name || "unknown",
        released_version: row.released_version || "",
        released_version_spec: row.released_version_spec || "",
        current_version: row.current_version || "",
        current_version_spec: row.current_version_spec || "",
        status: row.status || "unchanged",
      })),
    [comparisonData],
  );

  const managedPackages = normalizedData.filter((row) => row.package_type === "managed");
  const transitivePackages = normalizedData.filter((row) => row.package_type === "transitive");
  const visiblePackages = activeTab === "managed" ? managedPackages : transitivePackages;
  const serviceOptions = useMemo(() => {
    const values = Array.from(new Set(normalizedData.map((row) => row.service_name))).sort();
    return ["all", ...values];
  }, [normalizedData]);

  const filteredPackages = visiblePackages.filter((row) => {
    const q = searchQuery.trim().toLowerCase();
    const matchesSearch =
      !q ||
      (
      row.name.toLowerCase().includes(q) ||
      row.service_name.toLowerCase().includes(q) ||
      row.released_version.toLowerCase().includes(q) ||
      row.released_version_spec.toLowerCase().includes(q) ||
      row.current_version.toLowerCase().includes(q) ||
      row.current_version_spec.toLowerCase().includes(q) ||
      row.status.toLowerCase().includes(q)
      );
    const matchesDelta = showChangedOnly ? row.status !== "unchanged" : true;
    return matchesSearch && matchesDelta;
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loading />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-border bg-card p-4 lg:grid-cols-[auto_12rem_minmax(0,1fr)_auto] lg:items-center">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setActiveTab("managed");
              setSearchQuery("");
            }}
            className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors ${
              activeTab === "managed"
                ? "bg-background text-foreground ring-1 ring-border"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t("Managed")}
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{managedPackages.length}</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("transitive");
              setSearchQuery("");
            }}
            className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors ${
              activeTab === "transitive"
                ? "bg-background text-foreground ring-1 ring-border"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t("Transitive")}
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{transitivePackages.length}</span>
          </button>
        </div>
        <select
          value={selectedService}
          onChange={(e) => setSelectedService(e.target.value)}
          className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {serviceOptions.map((serviceName) => (
            <option key={serviceName} value={serviceName}>
              {serviceName === "all" ? t("All Services") : serviceName}
            </option>
          ))}
        </select>
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={
            activeTab === "managed" ? t("Search managed packages...") : t("Search transitive packages...")
          }
          className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none ring-offset-background placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
        />
        <button
          type="button"
          onClick={() => setShowChangedOnly((current) => !current)}
          className={`h-10 rounded-md border px-3 text-sm transition-colors ${
            showChangedOnly
              ? "border-border bg-muted text-foreground"
              : "border-border bg-background text-muted-foreground hover:text-foreground"
          }`}
        >
          {showChangedOnly ? t("Showing Changed Only") : t("Show Changed Only")}
        </button>
      </div>

      <div className="max-h-[60vh] overflow-auto rounded-lg border border-border bg-card">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b border-border bg-muted/30 text-xs text-muted-foreground">
              <th className="px-4 py-3 text-left font-semibold uppercase tracking-wider">{t("Package")}</th>
              <th className="px-4 py-3 text-left font-semibold uppercase tracking-wider">{t("Service")}</th>
              {activeTab === "managed" && (
                <th className="px-4 py-3 text-left font-semibold uppercase tracking-wider">{t("Released Spec")}</th>
              )}
              <th className="px-4 py-3 text-left font-semibold uppercase tracking-wider">{t("Released Version")}</th>
              <th className="px-4 py-3 text-left font-semibold uppercase tracking-wider">{t("Current Version")}</th>
              <th className="px-4 py-3 text-left font-semibold uppercase tracking-wider">{t("Status")}</th>
            </tr>
          </thead>
          <tbody>
            {filteredPackages.length === 0 ? (
              <tr>
                <td
                  colSpan={activeTab === "managed" ? 6 : 5}
                  className="px-4 py-10 text-center text-sm text-muted-foreground"
                >
                  {searchQuery ? t("No packages match your search.") : t("No packages found in this view.")}
                </td>
              </tr>
            ) : (
              filteredPackages.map((row) => (
                <tr
                  key={`${row.service_name}-${row.package_type}-${row.name}`}
                  className="border-b border-border/30 align-top last:border-b-0 hover:bg-muted/20"
                >
                  <td className="px-4 py-3 font-mono text-sm" title={row.name}>{row.name}</td>
                  <td className="px-4 py-3 text-muted-foreground">{row.service_name}</td>
                  {activeTab === "managed" && (
                    <td className="px-4 py-3 text-muted-foreground">{row.released_version_spec || "-"}</td>
                  )}
                  <td className="px-4 py-3">{row.released_version || "-"}</td>
                  <td className="px-4 py-3">{row.current_version || "-"}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${comparisonStatusClass(row.status)}`}
                    >
                      {t(formatComparisonStatus(row.status))}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ReleaseDocumentTab({ release, regionCode }: { release: ReleaseRecord; regionCode?: string | null }) {
  const { t } = useTranslation();
  const { data, isLoading } = useGetReleaseDocumentPreview({ releaseId: release.id, regionCode });
  const [showFallbackPreview, setShowFallbackPreview] = useState(false);
  const [showViewerAssist, setShowViewerAssist] = useState(false);

  useEffect(() => {
    setShowFallbackPreview(false);
    setShowViewerAssist(false);
  }, [release.id]);

  useEffect(() => {
    if (!data?.office_viewer_url || showFallbackPreview) return;
    const timer = window.setTimeout(() => {
      setShowViewerAssist(true);
    }, 5000);
    
    return () => window.clearTimeout(timer);
  }, [data?.office_viewer_url, showFallbackPreview]);

  const handleDownload = async () => {
    const response = await api.get(`${getURL("RELEASES")}/${release.id}/document/download`, {
      responseType: "blob",
      ...(regionCode ? { headers: { "X-Region-Code": regionCode } } : {}),
    });
    const blob = new Blob([response.data], {
      type: release.document_content_type ?? "application/octet-stream",
    });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = release.document_file_name ?? `${release.version}.docx`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loading />
      </div>
    );
  }

  if (!data?.has_document) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center text-sm text-muted-foreground">
        {t("No release document is available for this release.")}
      </div>
    );
  }

  const officeViewerUrl = data.office_viewer_url || "";
  const canTryOfficeViewer = Boolean(officeViewerUrl) && !showFallbackPreview;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="truncate text-sm font-medium text-foreground" title={data.file_name || release.document_file_name || ""}>
            {data.file_name || release.document_file_name}
          </div>
          <div className="text-xs text-muted-foreground">
            {t("Uploaded")}: {formatDateTime(data.document_uploaded_at || release.document_uploaded_at)}
            {" • "}
            {t("Size")}: {formatFileSize(data.document_size || release.document_size)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {officeViewerUrl && (
            <Button
              type="button"
              variant="outline"
              onClick={() => window.open(officeViewerUrl, "_blank", "noopener,noreferrer")}
            >
              {t("Open in Word Viewer")}
            </Button>
          )}
          <Button type="button" variant="outline" onClick={handleDownload}>
            {t("Download Document")}
          </Button>
        </div>
      </div>

      {canTryOfficeViewer ? (
        <div className="space-y-3">
          {showViewerAssist && (
            <div className="flex flex-col gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 md:flex-row md:items-center md:justify-between">
              <div>
                {t("If the Word-style preview does not open correctly, switch to the fallback preview or download the document.")}
              </div>
              <Button type="button" variant="outline" onClick={() => setShowFallbackPreview(true)}>
                {t("Use Fallback Preview")}
              </Button>
            </div>
          )}
          <div className="overflow-hidden rounded-lg border border-border bg-card">
            <iframe
              title={data.file_name || release.document_file_name || "Release Document"}
              src={officeViewerUrl}
              className="h-[72vh] w-full"
            />
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {officeViewerUrl
              ? t("Word-style preview could not be used for this document. Showing fallback document preview.")
              : t("Office-style preview is unavailable in this environment. Showing fallback document preview.")}
          </div>
          <div className="rounded-lg border border-border bg-card p-6">
            <div
              className="release-doc-html prose prose-sm max-w-none text-foreground [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:text-base [&_h3]:font-semibold [&_p]:mb-3 [&_table]:mb-4 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:px-3 [&_td]:py-2"
              dangerouslySetInnerHTML={{ __html: data.html }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function ViewReleaseDialog({
  release,
  open,
  onOpenChange,
  regionCode,
}: {
  release: ReleaseRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  regionCode?: string | null;
}) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("document");

  if (!release) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-6xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("Release {{version}}", { version: release.version })}</DialogTitle>
          <DialogDescription>
            {release.release_notes || t("Review the uploaded release document and the captured library snapshot.")}
          </DialogDescription>
        </DialogHeader>

        <Tabs key={release.id} value={activeTab} onValueChange={setActiveTab} className="space-y-4">
          <TabsList className="grid w-full grid-cols-2 rounded-lg border border-border bg-card p-1">
            <TabsTrigger value="document">{t("Release Document")}</TabsTrigger>
            <TabsTrigger value="libraries">{t("Packages")}</TabsTrigger>
          </TabsList>

          <TabsContent value="document" className="space-y-4">
            <ReleaseDocumentTab release={release} regionCode={regionCode} />
          </TabsContent>

          <TabsContent value="libraries" className="space-y-4">
            <ReleaseLibrariesTab releaseId={release.id} regionCode={regionCode} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function CreateReleaseDialog({
  open,
  onOpenChange,
  regionCode,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  regionCode?: string | null;
}) {
  const { t } = useTranslation();
  const { setSuccessData, setErrorData } = useAlertStore();
  const [bumpType, setBumpType] = useState<BumpType>("patch");
  const [notes, setNotes] = useState("");
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [selectedFileName, setSelectedFileName] = useState("");

  const createReleaseMutation = usePostBumpReleaseWithDocument({
    onSuccess: () => {
      setSuccessData({ title: t("Release created successfully.") });
      setNotes("");
      setDocumentFile(null);
      setSelectedFileName("");
      setBumpType("patch");
      onOpenChange(false);
    },
    onError: (err: any) => {
      setErrorData({
        title: err?.response?.data?.detail || err?.message || t("Failed to create release."),
      });
    },
  });

  const handleSubmit = () => {
    if (!documentFile) {
      setErrorData({ title: t("Please upload a .docx release document.") });
      return;
    }
    createReleaseMutation.mutate({
      bump_type: bumpType,
      release_notes: notes,
      document_file: documentFile,
      regionCode,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("Create Release")}</DialogTitle>
          <DialogDescription>
            {t("Publish a new release version with an uploaded Word document and the current library snapshot.")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-2">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{t("Version Bump")}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {BUMP_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setBumpType(option.value)}
                  className={`rounded-lg border px-4 py-3 text-left transition-colors ${
                    bumpType === option.value
                      ? "border-primary bg-primary/5 text-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <div className="font-medium">{t(option.label)}</div>
                  <div className="mt-1 text-xs">{t(option.description)}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{t("Release Notes")}</p>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              placeholder={t("Add an optional release summary.")}
            />
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{t("Release Document")}</p>
            <div className="rounded-lg border border-dashed border-border bg-muted/10 p-4">
              <label
                htmlFor="release-document-upload"
                className="flex cursor-pointer items-center justify-between gap-3 rounded-md border border-border bg-background px-4 py-3 transition-colors hover:border-primary/40"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-foreground" title={selectedFileName}>
                    {selectedFileName || t("Select release document")}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {documentFile
                      ? `${formatFileSize(documentFile.size)} • .docx`
                      : t("Upload one Word document for this release")}
                  </div>
                </div>
                <span className="shrink-0 rounded-md border border-border bg-muted px-3 py-2 text-sm font-medium text-foreground">
                  {t("Choose File")}
                </span>
              </label>
              <input
                id="release-document-upload"
                type="file"
                accept=".docx"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null;
                  setDocumentFile(file);
                  setSelectedFileName(file?.name ?? "");
                }}
              />
              <p className="mt-2 text-xs text-muted-foreground">
                {documentFile ? (
                  <span title={documentFile.name}>{documentFile.name}</span>
                ) : (
                  t("Only .docx files are supported. The document will be stored securely in release documents.")
                )}
              </p>
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("Cancel")}
            </Button>
            <Button type="button" onClick={handleSubmit} disabled={createReleaseMutation.isPending}>
              {createReleaseMutation.isPending ? t("Creating...") : t("Create Release")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function ReleaseManagementPage() {
  const { t } = useTranslation();
  const { permissions, userData } = useContext(AuthContext);
  const normalizedRole = String(userData?.role || "").trim().toLowerCase();
  const isRootAdmin = normalizedRole === "root";
  const regions = useRegionStore((s) => s.regions);
  const selectedRegionCode = useRegionStore((s) => s.selectedRegionCode);
  const setSelectedRegion = useRegionStore((s) => s.setSelectedRegion);
  const fetchRegions = useRegionStore((s) => s.fetchRegions);
  const releaseRegionCode = isRootAdmin ? selectedRegionCode : null;
  const { data: currentRelease, isLoading: isCurrentLoading } = useGetCurrentRelease({ regionCode: releaseRegionCode });
  const { data: releases = [], isLoading: isReleasesLoading } = useGetReleases({ regionCode: releaseRegionCode });
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedRelease, setSelectedRelease] = useState<ReleaseRecord | null>(null);

  useEffect(() => {
    if (isRootAdmin) {
      fetchRegions();
    }
  }, [isRootAdmin, fetchRegions]);

  const isRemoteRegion = useMemo(() => {
    if (!isRootAdmin || !selectedRegionCode || !regions.length) return false;
    const hub = regions.find((r) => r.is_hub);
    return hub ? hub.code !== selectedRegionCode : false;
  }, [isRootAdmin, selectedRegionCode, regions]);

  const canPublishRelease = permissions?.includes("publish_release");
  const pageTitle = isRootAdmin ? t("Release Management") : t("Release Versions");
  const pageSubtitle = isRootAdmin
    ? t("Review versioned releases, release documents, and captured library snapshots")
    : t("Review released versions, release documents, and captured package snapshots");
  const sortedReleases = useMemo(
    () => [...releases].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [releases],
  );

  useEffect(() => {
    setSelectedRelease(null);
    setCreateOpen(false);
  }, [releaseRegionCode]);

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

  return (
    <div className="flex h-full flex-col bg-background">
      <div className="border-b border-border bg-background px-8 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground md:text-2xl">
              {pageTitle}
            </h1>
            <p className="text-sm text-muted-foreground">
              {pageSubtitle}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 self-start">
            {isRootAdmin && regions.length > 1 && (
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-muted-foreground" />
                <Select value={selectedRegionCode ?? ""} onValueChange={setSelectedRegion}>
                  <SelectTrigger className="h-9 w-[170px] text-sm">
                    <SelectValue placeholder={t("Select Region")} />
                  </SelectTrigger>
                  <SelectContent>
                    {regions.map((region) => (
                      <SelectItem key={region.code} value={region.code}>
                        {region.name}
                        {region.is_hub ? " (Hub)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {canPublishRelease && (
              <Button type="button" onClick={() => setCreateOpen(true)} className="self-start">
                {t("Create Release")}
              </Button>
            )}
          </div>
        </div>
      </div>

      {isRootAdmin && isRemoteRegion && selectedRegionCode && (
        <div className="border-b border-amber-200 bg-amber-50 px-8 py-2.5">
          <div className="flex items-center justify-between gap-4">
            <p className="text-xs text-amber-800">
              {t("Viewing and managing release data for {{region}} from hub.", {
                region: regions.find((r) => r.code === selectedRegionCode)?.name ?? selectedRegionCode,
              })}
            </p>
            <button
              type="button"
              onClick={() => {
                const hub = regions.find((r) => r.is_hub);
                if (hub) setSelectedRegion(hub.code);
              }}
              className="text-xs font-medium text-amber-700 hover:underline"
            >
              {t("Back to Hub")}
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-8">
        <div className="space-y-6">
          <section className="rounded-lg border border-border bg-card px-6 py-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)] xl:items-center">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {t("Current Release")}
                </p>
                {isCurrentLoading ? (
                  <div className="mt-3 flex items-center gap-3 text-sm text-muted-foreground">
                    <Loading />
                  </div>
                ) : currentRelease ? (
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <span className="text-2xl font-semibold text-foreground">v{currentRelease.version}</span>
                    <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700">
                      {t("Active")}
                    </span>
                    <span
                      className="max-w-[28rem] truncate text-sm text-muted-foreground"
                      title={currentRelease.release_notes || t("No release summary was provided for the active release.")}
                    >
                      {currentRelease.release_notes || t("No release summary was provided for the active release.")}
                    </span>
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-muted-foreground">{t("No active release found.")}</p>
                )}
              </div>

              {currentRelease && (
                <div className="grid min-w-0 gap-4 sm:grid-cols-[9rem_minmax(0,1fr)_7rem_auto] sm:items-center">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t("Start Date")}
                    </div>
                    <div className="mt-1 text-sm text-foreground">{formatDate(currentRelease.start_date)}</div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t("Document")}
                    </div>
                    <div className="mt-1 truncate text-sm text-foreground" title={currentRelease.document_file_name || ""}>
                      {currentRelease.document_file_name || "-"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t("Packages")}
                    </div>
                    <div className="mt-1 text-sm text-foreground">{currentRelease.package_count ?? "-"}</div>
                  </div>
                  <div className="flex sm:justify-end">
                    <Button type="button" variant="outline" size="sm" onClick={() => setSelectedRelease(currentRelease)}>
                      {t("View Release")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold text-foreground">{t("Release History")}</h2>
              <p className="text-sm text-muted-foreground">
                {t("Open any release to preview the document and review the captured library set.")}
              </p>
            </div>

            <div className="rounded-lg border border-border bg-card overflow-hidden">
              <style>{`
                .rel-table-scroll::-webkit-scrollbar { height: 0; }
                .rel-table-scroll { scrollbar-width: none; }
                .rel-mirror-bar::-webkit-scrollbar { height: 8px; }
                .rel-mirror-bar::-webkit-scrollbar-track { background: hsl(var(--muted)); border-radius: 9999px; }
                .rel-mirror-bar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground)); border-radius: 9999px; }
                .rel-mirror-bar::-webkit-scrollbar-thumb:hover { background: hsl(var(--foreground) / 0.8); }
                .rel-mirror-bar { scrollbar-width: thin; scrollbar-color: hsl(var(--muted-foreground)) hsl(var(--muted)); }
              `}</style>
              <div className="flex flex-col max-h-[58vh]">
              <div ref={tableScrollRef} className="rel-table-scroll flex-1 overflow-auto">
                <table className="w-full min-w-[980px] text-sm">
                  <thead className="sticky top-0 z-10 bg-card">
                    <tr className="border-b border-border bg-muted/30 text-xs uppercase tracking-wider text-muted-foreground">
                      <th className="px-4 py-3 text-left font-semibold">{t("Version")}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t("Status")}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t("Document")}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t("Created")}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t("Packages")}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t("Notes")}</th>
                      <th className="px-4 py-3 text-center font-semibold">{t("Actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {isReleasesLoading ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-12 text-center">
                          <div className="flex justify-center">
                            <Loading />
                          </div>
                        </td>
                      </tr>
                    ) : sortedReleases.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-12 text-center text-sm text-muted-foreground">
                          {t("No releases found")}
                        </td>
                      </tr>
                    ) : (
                      sortedReleases.map((release) => (
                        <tr key={release.id} className="border-b border-border/30 align-top last:border-b-0 hover:bg-muted/20">
                          <td className="px-4 py-4">
                            <div className="font-medium text-foreground">v{release.version}</div>
                            <div className="text-xs text-muted-foreground">
                              {release.major}.{release.minor}.{release.patch}
                            </div>
                          </td>
                          <td className="px-4 py-4">
                            <span
                              className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
                                release.end_date === ACTIVE_END_DATE
                                  ? "bg-emerald-100 text-emerald-700"
                                  : "bg-muted text-muted-foreground"
                              }`}
                            >
                              {release.end_date === ACTIVE_END_DATE ? t("Active") : t("Closed")}
                            </span>
                          </td>
                          <td className="px-4 py-4" title={release.document_file_name || ""}>
                            <div className="max-w-[280px] truncate text-foreground">
                              {release.document_file_name || "-"}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {release.has_document ? t("Uploaded") : t("Unavailable")}
                            </div>
                          </td>
                          <td className="px-4 py-4 text-muted-foreground">{formatDate(release.created_at)}</td>
                          <td className="px-4 py-4 text-foreground">{release.package_count ?? "-"}</td>
                          <td className="px-4 py-4 text-muted-foreground" title={release.release_notes || ""}>
                            <div className="max-w-[320px] line-clamp-2 break-words">{release.release_notes || "-"}</div>
                          </td>
                          <td className="px-4 py-4 text-center">
                            <Button type="button" variant="outline" size="sm" onClick={() => setSelectedRelease(release)}>
                              {t("View")}
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div ref={mirrorRef} className="rel-mirror-bar flex-shrink-0 overflow-x-scroll overflow-y-hidden" style={{ height: 12 }}>
                <div ref={phantomRef} style={{ height: 1 }} />
              </div>
            </div>
          </div>
          </section>
        </div>
      </div>

      <CreateReleaseDialog open={createOpen} onOpenChange={setCreateOpen} regionCode={releaseRegionCode} />
      <ViewReleaseDialog
        key={selectedRelease?.id ?? "release-view-dialog"}
        release={selectedRelease}
        regionCode={releaseRegionCode}
        open={Boolean(selectedRelease)}
        onOpenChange={(open) => {
          if (!open) setSelectedRelease(null);
        }}
      />
    </div>
  );
}
