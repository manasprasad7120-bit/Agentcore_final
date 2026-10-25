import { useState, useEffect } from "react";
import type { PublicClientApplication, AccountInfo } from "@azure/msal-browser";
import { Client } from "@microsoft/microsoft-graph-client";
import { getSharepointMsalInstance, initSharepointMsal, sharepointLoginRequest } from "./sharepointMsalConfig";
import {
  Loader2,
  Folder,
  File as FileIcon,
  FileText,
  FileSpreadsheet,
  FileImage,
  ChevronRight,
  X,
  ArrowLeft,
  Check,
} from "lucide-react";
import { useTranslation } from "react-i18next";

interface DriveItem {
  id: string;
  name: string;
  folder?: any;
  file?: { mimeType?: string };
  size?: number;
  webUrl: string;
  parentReference?: { driveId: string; id: string };
}

interface SharePointFilePickerProps {
  isOpen: boolean;
  onDismiss: () => void;
  onFilesSelected: (files: File[]) => void;
}

export default function SharePointFilePicker({
  isOpen,
  onDismiss,
  onFilesSelected,
}: SharePointFilePickerProps) {
  const { t } = useTranslation();
  const [spMsal, setSpMsal] = useState<PublicClientApplication | null>(null);
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [items, setItems] = useState<DriveItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [folderStack, setFolderStack] = useState<
    { id: string; name: string }[]
  >([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [spConsented, setSpConsented] = useState(false);

  // Initialize the SharePoint MSAL instance when the picker opens.
  // By the time the user reads the consent screen and clicks
  // "Accept & Continue", the async init is long finished and the click
  // handler can call loginPopup synchronously.
  useEffect(() => {
    if (!isOpen) return;
    // Already have it — just seed account
    const existing = getSharepointMsalInstance();
    if (existing) {
      setSpMsal(existing);
      const accts = existing.getAllAccounts();
      if (accts.length > 0) {
        existing.setActiveAccount(accts[0]);
        setAccount(accts[0]);
      }
      return;
    }
    // First time — create and initialize
    let cancelled = false;
    initSharepointMsal()
      .then((inst) => {
        if (cancelled) return;
        setSpMsal(inst);
        const accts = inst.getAllAccounts();
        if (accts.length > 0) {
          inst.setActiveAccount(accts[0]);
          setAccount(accts[0]);
        }
      })
      .catch((err) => {
        if (!cancelled) console.error("SharePoint MSAL init failed:", err);
      });
    return () => { cancelled = true; };
  }, [isOpen]);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setFolderStack([]);
      setSelectedIds(new Set());
      setError(null);
      setItems([]);
    }
  }, [isOpen]);

  // If already consented and modal opens, fetch files immediately
  useEffect(() => {
    if (isOpen && spConsented) {
      fetchFiles("root");
    }
  }, [isOpen, spConsented]);

  /* ── MSAL helpers ─────────────────────────────────────────────── */

  const handleAcceptAndContinue = async () => {
    if (!spMsal) {
      setError("SharePoint sign-in is still loading. Please try again.");
      return;
    }

    setLoading(true);
    setError(null);

    // Call loginPopup / acquireTokenPopup SYNCHRONOUSLY from click — no
    // awaits before this point so the browser keeps the user-gesture token.
    const accounts = spMsal.getAllAccounts();
    const popupPromise =
      accounts.length === 0
        ? spMsal.loginPopup(sharepointLoginRequest)
        : spMsal
            .acquireTokenSilent({
              ...sharepointLoginRequest,
              account: accounts[0],
            })
            .catch(() =>
              spMsal.acquireTokenPopup({
                ...sharepointLoginRequest,
                account: accounts[0],
              }),
            );

    try {
      const result = await popupPromise;
      if (result?.account) {
        spMsal.setActiveAccount(result.account);
        setAccount(result.account);
      } else if (accounts[0]) {
        spMsal.setActiveAccount(accounts[0]);
        setAccount(accounts[0]);
      }
      setSpConsented(true);
      await fetchFiles("root");
    } catch (e) {
      console.error("SharePoint login failed:", e);
      setError("Authentication failed. Please try again.");
      setLoading(false);
    }
  };

  const getGraphClient = async (): Promise<Client> => {
    if (!spMsal) {
      throw new Error("SharePoint MSAL not initialized.");
    }
    const activeAccount =
      spMsal.getActiveAccount() ?? spMsal.getAllAccounts()[0];
    if (!activeAccount) {
      throw new Error("No SharePoint account — user must sign in first.");
    }
    const request = { ...sharepointLoginRequest, account: activeAccount };
    try {
      const response = await spMsal.acquireTokenSilent(request);
      return Client.init({
        authProvider: (done) => done(null, response.accessToken),
      });
    } catch {
      const response = await spMsal.acquireTokenPopup(request);
      return Client.init({
        authProvider: (done) => done(null, response.accessToken),
      });
    }
  };

  /* ── Data fetching ────────────────────────────────────────────── */

  const fetchFiles = async (folderId: string) => {
    setLoading(true);
    setError(null);
    try {
      const client = await getGraphClient();
      const path =
        folderId === "root"
          ? "/me/drive/root/children"
          : `/me/drive/items/${folderId}/children`;
      const response = await client.api(path).get();
      setItems(response.value || []);
      setSelectedIds(new Set());
    } catch (err) {
      console.error("Error fetching files:", err);
      setError("Failed to load files");
    } finally {
      setLoading(false);
    }
  };

  /* ── Interactions ─────────────────────────────────────────────── */

  const openFolder = (item: DriveItem) => {
    setFolderStack((prev) => [...prev, { id: item.id, name: item.name }]);
    fetchFiles(item.id);
  };

  const goBack = () => {
    const newStack = [...folderStack];
    newStack.pop();
    setFolderStack(newStack);
    const parentId =
      newStack.length > 0 ? newStack[newStack.length - 1].id : "root";
    fetchFiles(parentId);
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleItemClick = (item: DriveItem) => {
    if (item.folder) {
      openFolder(item);
    } else {
      toggleSelect(item.id);
    }
  };

  const handleDownloadSelected = async () => {
    if (selectedIds.size === 0 || !spMsal) return;
    setLoading(true);
    try {
      const activeAccount =
        spMsal.getActiveAccount() ?? spMsal.getAllAccounts()[0];
      if (!activeAccount) throw new Error("No SharePoint account");

      // Get a fresh Graph access token to hand to our backend.
      const tokenResp = await spMsal.acquireTokenSilent({
        ...sharepointLoginRequest,
        account: activeAccount,
      });
      const accessToken = tokenResp.accessToken;

      const filesToDownload = items.filter(
        (f) => selectedIds.has(f.id) && !f.folder,
      );
      const downloaded: File[] = [];

      // Route the download through our backend to avoid the CORS issue
      // when Graph 302-redirects to the SharePoint CDN
      // (mothersongroup-my.sharepoint.com), which doesn't allow
      // cross-origin reads from localhost:3000.
      for (const item of filesToDownload) {
        try {
          const res = await fetch("/api/sharepoint-user/download", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              access_token: accessToken,
              item_id: item.id,
              drive_id: item.parentReference?.driveId ?? "",
              filename: item.name,
            }),
          });
          if (!res.ok) {
            const text = await res.text();
            throw new Error(`HTTP ${res.status}: ${text}`);
          }
          const data = await res.json();
          // Decode base64 → bytes → File
          const binary = atob(data.content_base64);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          downloaded.push(
            new File([bytes], item.name, {
              type: item.file?.mimeType || "application/octet-stream",
            }),
          );
        } catch (err) {
          console.error(`Failed to download ${item.name}:`, err);
        }
      }

      onFilesSelected(downloaded);
      onDismiss();
    } catch (err) {
      console.error("Download error:", err);
      setError("Failed to download files");
    } finally {
      setLoading(false);
    }
  };

  /* ── File icon helper ─────────────────────────────────────────── */

  const ItemIcon = ({ item }: { item: DriveItem }) => {
    if (item.folder) return <Folder size={20} className="shrink-0 text-blue-500" />;
    const ext = item.name.split(".").pop()?.toLowerCase();
    if (["jpg", "jpeg", "png", "gif", "bmp", "webp"].includes(ext || ""))
      return <FileImage size={20} className="shrink-0 text-purple-500" />;
    if (["xls", "xlsx", "csv"].includes(ext || ""))
      return <FileSpreadsheet size={20} className="shrink-0 text-green-600" />;
    if (["doc", "docx", "pdf", "txt", "ppt", "pptx"].includes(ext || ""))
      return <FileText size={20} className="shrink-0 text-blue-600" />;
    return <FileIcon size={20} className="shrink-0 text-muted-foreground" />;
  };

  if (!isOpen) return null;

  /* ── Render ───────────────────────────────────────────────────── */

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50">
      <div className="flex max-h-[80vh] w-full max-w-xl flex-col rounded-2xl border border-border bg-popover shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-3">
            {spConsented && folderStack.length > 0 && (
              <button
                onClick={goBack}
                className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <ArrowLeft size={18} />
              </button>
            )}
            <h2 className="text-base font-semibold text-foreground">
              {spConsented
                ? t("Select a file from SharePoint")
                : t("Permissions Requested")}
            </h2>
          </div>
          <button
            onClick={onDismiss}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X size={18} />
          </button>
        </div>

        {/* Breadcrumb (when logged in) */}
        {spConsented && folderStack.length > 0 && (
          <div className="flex items-center gap-1 border-b border-border bg-muted/30 px-5 py-2 text-xs text-muted-foreground">
            <button
              onClick={() => {
                setFolderStack([]);
                fetchFiles("root");
              }}
              className="hover:text-foreground hover:underline"
            >
              {t("Root")}
            </button>
            {folderStack.map((f) => (
              <span key={f.id} className="flex items-center gap-1">
                <ChevronRight size={12} />
                <span>{f.name}</span>
              </span>
            ))}
          </div>
        )}

        {/* Body */}
        {!spConsented ? (
          /* ── Consent screen (matching template) ── */
          <div className="flex flex-1 flex-col items-center px-6 py-8 text-center">
            <div className="mb-4 text-5xl">🔒</div>
            <p className="mb-1 text-lg font-semibold text-foreground">
              {t("MiBuddy SharePoint connector needs your permission")}
            </p>
            <p className="mb-5 text-sm text-muted-foreground">
              {t("To access your SharePoint files, we need you to sign in.")}
            </p>

            <div className="mb-6 w-full rounded-lg border border-border bg-muted/30 px-5 py-4 text-left">
              <p className="mb-3 text-sm font-semibold text-foreground">
                {t("This will allow MiBuddy to:")}
              </p>
              <ul className="flex flex-col gap-3">
                <li className="flex items-center gap-3 text-sm text-foreground">
                  <span className="font-bold text-green-600">✓</span>
                  {t("Sign you in and read your profile")}
                </li>
                <li className="flex items-center gap-3 text-sm text-foreground">
                  <span className="font-bold text-green-600">✓</span>
                  {t("Read your files and folders present in SharePoint")}
                </li>
                <li className="flex items-center gap-3 text-sm text-foreground">
                  <span className="font-bold text-green-600">✓</span>
                  {t("Read items in all site collections")}
                </li>
              </ul>
            </div>

            {error && (
              <div className="mb-4 w-full rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300">
                {error}
              </div>
            )}

            <div className="flex items-center gap-3">
              <button
                onClick={handleAcceptAndContinue}
                disabled={loading}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {loading && <Loader2 size={16} className="animate-spin" />}
                {loading ? t("Connecting...") : t("Accept & Continue")}
              </button>
              <button
                onClick={onDismiss}
                className="rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-foreground hover:bg-accent"
              >
                {t("Cancel")}
              </button>
            </div>
          </div>
        ) : (
          /* ── File browser ── */
          <>
            <div
              className="flex-1 overflow-y-auto"
              style={{ scrollbarWidth: "thin", minHeight: "300px" }}
            >
              {loading ? (
                <div className="flex flex-col items-center justify-center gap-3 py-16">
                  <Loader2 size={28} className="animate-spin text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">
                    {t("Loading your content...")}
                  </span>
                </div>
              ) : items.length === 0 ? (
                <div className="flex flex-col items-center py-16 text-muted-foreground">
                  <div className="mb-2 text-4xl">📁</div>
                  <span className="text-sm">{t("This folder is empty")}</span>
                </div>
              ) : (
                items.map((item) => {
                  const isSelected = selectedIds.has(item.id);
                  return (
                    <button
                      key={item.id}
                      onClick={() => handleItemClick(item)}
                      className={`flex w-full items-center gap-3 border-b border-border/50 px-5 py-3 text-left transition-colors hover:bg-accent/50 ${
                        isSelected ? "bg-blue-50 dark:bg-blue-950/20" : ""
                      }`}
                    >
                      {/* Checkbox for files, spacer for folders */}
                      <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                        {!item.folder ? (
                          <div
                            className={`flex h-5 w-5 items-center justify-center rounded-full border-2 transition-colors ${
                              isSelected
                                ? "border-blue-600 bg-blue-600"
                                : "border-muted-foreground/40"
                            }`}
                          >
                            {isSelected && (
                              <Check size={12} className="text-white" />
                            )}
                          </div>
                        ) : (
                          <span className="w-5" />
                        )}
                      </div>

                      <ItemIcon item={item} />

                      <div className="min-w-0 flex-1">
                        <div
                          className={`truncate text-sm ${
                            item.folder ? "font-semibold" : ""
                          } text-foreground`}
                        >
                          {item.name}
                        </div>
                        {item.size && !item.folder && (
                          <div className="text-xs text-muted-foreground">
                            {(item.size / 1024).toFixed(1)} KB
                          </div>
                        )}
                      </div>

                      {item.folder && (
                        <ChevronRight
                          size={16}
                          className="shrink-0 text-muted-foreground"
                        />
                      )}
                    </button>
                  );
                })
              )}
            </div>

            {/* Footer with action buttons */}
            <div className="flex items-center justify-end gap-3 border-t border-border px-5 py-3">
              <button
                onClick={onDismiss}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-accent"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={handleDownloadSelected}
                disabled={selectedIds.size === 0 || loading}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors ${
                  selectedIds.size > 0 && !loading
                    ? "bg-blue-600 hover:bg-blue-700"
                    : "cursor-not-allowed bg-muted text-muted-foreground"
                }`}
              >
                {loading ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  `${t("Select")}${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
