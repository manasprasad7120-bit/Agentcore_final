import { useCallback, useEffect, useState } from "react";
import useAgentStore from "@/stores/agentStore";
import { usePostPublishToTeams } from "@/controllers/API/queries/teams/use-post-publish-to-teams";
import { useDeleteUnpublishFromTeams } from "@/controllers/API/queries/teams/use-delete-unpublish-from-teams";
import { useGetTeamsStatus } from "@/controllers/API/queries/teams/use-get-teams-status";
import { usePostSyncTeamsApp } from "@/controllers/API/queries/teams/use-post-sync-teams-app";
import { useGetTeamsOAuthStatus } from "@/controllers/API/queries/teams/use-get-teams-oauth-status";
import type { TeamsPublishStatus } from "@/types/teams";

interface TeamsPublishModalProps {
  open: boolean;
  setOpen: (open: boolean) => void;
}

const statusColors: Record<TeamsPublishStatus, string> = {
  DRAFT: "bg-yellow-100 text-yellow-800",
  UPLOADED: "bg-blue-100 text-blue-800",
  PUBLISHED: "bg-green-100 text-green-800",
  FAILED: "bg-red-100 text-red-800",
  UNPUBLISHED: "bg-gray-100 text-gray-800",
};

const TeamsPublishModal = ({ open, setOpen }: TeamsPublishModalProps) => {
  const agentId = useAgentStore((state) => state.currentAgent?.id);
  const agentName = useAgentStore((state) => state.currentAgent?.name);
  const agentDescription = useAgentStore(
    (state) => state.currentAgent?.description,
  );

  const [displayName, setDisplayName] = useState(agentName || "");
  const [shortDescription, setShortDescription] = useState(
    agentDescription || "",
  );
  const [botAppId, setBotAppId] = useState("");
  const [botAppSecret, setBotAppSecret] = useState("");
  const [currentStatus, setCurrentStatus] =
    useState<TeamsPublishStatus | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [lastError, setLastError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [teamsExternalId, setTeamsExternalId] = useState<string | null>(null);
  const [hasOwnBot, setHasOwnBot] = useState(false);
  const [publishedBotAppId, setPublishedBotAppId] = useState<string | null>(
    null,
  );
  const [msConnected, setMsConnected] = useState(false);
  const [checkingConnection, setCheckingConnection] = useState(false);
  // Whether the connected user's token includes AppCatalog.ReadWrite.All.
  // When false, we keep the OAuth flow available (so users can connect /
  // disconnect) but disable Publish/Sync/Unpublish with a clear tooltip.
  // Defaults to true so legacy tokens (no granted_scopes field stored)
  // behave permissively — backend returns clean 403 if it actually fails.
  const [publishingAvailable, setPublishingAvailable] = useState(true);

  const publishMutation = usePostPublishToTeams();
  const unpublishMutation = useDeleteUnpublishFromTeams();
  const statusMutation = useGetTeamsStatus();
  const syncMutation = usePostSyncTeamsApp();
  const oauthStatusMutation = useGetTeamsOAuthStatus();

  // Check Microsoft connection status and Teams publish status when modal opens
  useEffect(() => {
    if (open && agentId) {
      setDisplayName(agentName || "");
      setShortDescription(agentDescription || "");
      setBotAppId("");
      setBotAppSecret("");
      checkOAuthStatus();
      fetchStatus();
    }
  }, [open, agentId]);

  // Listen for OAuth popup messages
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === "teams-oauth-success") {
        setMsConnected(true);
        setStatusMessage("Microsoft account connected successfully!");
        // Re-fetch status so we learn whether the freshly-issued token
        // actually contains AppCatalog.ReadWrite.All (it may not, if the
        // tenant admin only consented to read-level scopes).
        checkOAuthStatus();
      } else if (event.data?.type === "teams-oauth-error") {
        setStatusMessage(
          `Connection failed: ${event.data.description || event.data.error}`,
        );
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  const checkOAuthStatus = useCallback(() => {
    setCheckingConnection(true);
    oauthStatusMutation.mutate(undefined, {
      onSuccess: (data) => {
        setMsConnected(data.connected);
        // publishing_available may be omitted in older builds — default to
        // true (permissive) when the field is not present.
        setPublishingAvailable(data.publishing_available ?? true);
        setCheckingConnection(false);
      },
      onError: () => {
        setMsConnected(false);
        setPublishingAvailable(true); // permissive fallback on error
        setCheckingConnection(false);
      },
    });
  }, []);

  const fetchStatus = () => {
    if (!agentId) return;
    statusMutation.mutate(
      { agent_id: agentId },
      {
        onSuccess: (data) => {
          setCurrentStatus(data.status);
          setLastError(data.last_error || null);
          setTeamsExternalId(data.teams_external_id || null);
          setHasOwnBot(data.has_own_bot || false);
          setPublishedBotAppId(data.bot_app_id || null);
        },
        onError: () => {
          setCurrentStatus(null);
          setLastError(null);
          setHasOwnBot(false);
          setPublishedBotAppId(null);
        },
      },
    );
  };

  const handleConnectMicrosoft = () => {
    const width = 600;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    window.open(
      "/api/teams/oauth/authorize",
      "teams-oauth",
      `width=${width},height=${height},left=${left},top=${top},popup=yes`,
    );
  };

  const handlePublish = () => {
    if (!agentId) return;
    setLoading(true);
    setStatusMessage("");
    publishMutation.mutate(
      {
        agent_id: agentId,
        display_name: displayName || undefined,
        short_description: shortDescription || undefined,
        bot_app_id: botAppId.trim() || undefined,
        bot_app_secret: botAppSecret.trim() || undefined,
      },
      {
        onSuccess: (data) => {
          setCurrentStatus(data.status as TeamsPublishStatus);
          setStatusMessage(data.message);
          setLastError(null);
          setTeamsExternalId(data.teams_external_id || null);
          setLoading(false);
        },
        onError: (error: any) => {
          const detail =
            error?.response?.data?.detail || "Failed to publish to Teams";
          setStatusMessage(detail);
          setLoading(false);
          if (error?.response?.status === 401) {
            setMsConnected(false);
          }
        },
      },
    );
  };

  const handleUnpublish = () => {
    if (!agentId) return;
    setLoading(true);
    setStatusMessage("");
    unpublishMutation.mutate(
      { agent_id: agentId },
      {
        onSuccess: (data) => {
          setCurrentStatus(data.status as TeamsPublishStatus);
          setStatusMessage(data.message);
          setLoading(false);
        },
        onError: (error: any) => {
          setStatusMessage(
            error?.response?.data?.detail || "Failed to unpublish",
          );
          setLoading(false);
        },
      },
    );
  };

  const handleSync = () => {
    if (!agentId) return;
    setLoading(true);
    setStatusMessage("");
    syncMutation.mutate(
      { agent_id: agentId },
      {
        onSuccess: (data) => {
          setStatusMessage(data.message);
          setLoading(false);
        },
        onError: (error: any) => {
          setStatusMessage(
            error?.response?.data?.detail || "Failed to sync",
          );
          setLoading(false);
        },
      },
    );
  };

  const handleClose = () => {
    setStatusMessage("");
    setOpen(false);
  };

  if (!open) return null;

  const isPublished = currentStatus === "PUBLISHED";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="fixed left-[50%] top-[50%] z-50 w-full max-w-md translate-x-[-50%] translate-y-[-50%] rounded-lg border border-border bg-card p-6 shadow-lg">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Publish to Microsoft Teams</h2>
          <button
            onClick={handleClose}
            className="rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Microsoft Connection Status */}
        <div className="mb-4 rounded-md border border-border p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div
                className={`h-2 w-2 rounded-full ${msConnected ? "bg-green-500" : "bg-gray-400"}`}
              />
              <span className="text-sm text-muted-foreground">
                {checkingConnection
                  ? "Checking..."
                  : msConnected
                    ? "Microsoft account connected"
                    : "Microsoft account not connected"}
              </span>
            </div>
            {!msConnected && !checkingConnection && (
              <button
                onClick={handleConnectMicrosoft}
                className="rounded-md bg-[#0078d4] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#006cbe]"
              >
                Connect
              </button>
            )}
          </div>
        </div>

        {/* Status Badge */}
        {currentStatus && (
          <div className="mb-4">
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusColors[currentStatus]}`}
            >
              {currentStatus}
            </span>
            {lastError && currentStatus !== "PUBLISHED" && (
              <p className="mt-1 text-xs text-red-500">{lastError}</p>
            )}
          </div>
        )}

        {/* Dedicated bot indicator */}
        {isPublished && hasOwnBot && publishedBotAppId && (
          <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
            <div className="h-2 w-2 rounded-full bg-blue-500" />
            <span>
              Dedicated bot ({publishedBotAppId.slice(0, 8)}...)
            </span>
          </div>
        )}

        {/* Form - shown when not published */}
        {!isPublished && (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                Display Name
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                maxLength={30}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="App name in Teams"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {displayName.length}/30 characters
              </p>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                Description
              </label>
              <textarea
                value={shortDescription}
                onChange={(e) => setShortDescription(e.target.value)}
                maxLength={80}
                rows={2}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="Short description for the Teams app"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {shortDescription.length}/80 characters
              </p>
            </div>

            {/* Bot Registration Credentials */}
            <div className="rounded-md border border-border p-3">
              <p className="mb-2 text-xs font-medium text-foreground">
                Bot Registration (optional)
              </p>
              <p className="mb-3 text-xs text-muted-foreground">
                Provide a dedicated Azure Bot registration for this agent. If
                left empty, the shared global bot will be used.
              </p>
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">
                    Bot App ID
                  </label>
                  <input
                    type="text"
                    value={botAppId}
                    onChange={(e) => setBotAppId(e.target.value)}
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder="Azure AD App ID"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-muted-foreground">
                    Bot App Secret
                  </label>
                  <input
                    type="password"
                    value={botAppSecret}
                    onChange={(e) => setBotAppSecret(e.target.value)}
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder="Azure AD App Secret"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Status Message */}
        {statusMessage && (
          <p className="mt-3 text-sm text-muted-foreground">{statusMessage}</p>
        )}

        {/* Open in Teams Link */}
        {isPublished && teamsExternalId && (
          <a
            href={`https://teams.microsoft.com/l/app/${teamsExternalId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-[#0078d4] hover:underline"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            Open in Teams
          </a>
        )}

        {/* Actions */}
        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={handleClose}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-accent"
          >
            Close
          </button>

          {isPublished ? (
            <>
              <button
                onClick={handleSync}
                disabled={loading || !msConnected || !publishingAvailable}
                title={
                  !publishingAvailable && msConnected
                    ? "AppCatalog.ReadWrite.All is not granted on the connected Microsoft account. Ask your tenant admin to grant it."
                    : undefined
                }
                className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "Syncing..." : "Re-sync"}
              </button>
              <button
                onClick={handleUnpublish}
                disabled={loading || !publishingAvailable}
                title={
                  !publishingAvailable && msConnected
                    ? "AppCatalog.ReadWrite.All is not granted — cannot remove from the Teams catalog."
                    : undefined
                }
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "Removing..." : "Unpublish"}
              </button>
            </>
          ) : (
            <button
              onClick={handlePublish}
              disabled={
                loading ||
                !displayName.trim() ||
                !msConnected ||
                !publishingAvailable
              }
              title={
                !publishingAvailable && msConnected
                  ? "Publishing requires AppCatalog.ReadWrite.All. Ask your tenant admin to grant it, then reconnect your Microsoft account."
                  : undefined
              }
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Publishing..." : "Publish to Teams"}
            </button>
          )}
        </div>

        {/* Permission hint when connected but missing publish scope */}
        {msConnected && !publishingAvailable && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <strong>Publishing not available:</strong> The connected Microsoft
            account&apos;s token is missing the{" "}
            <code>AppCatalog.ReadWrite.All</code> permission. Agents that are
            already published continue to receive bot messages normally — but
            this flow can&apos;t install a new app, re-sync it, or remove it
            from the Teams catalog. Ask your Azure AD admin to grant this
            delegated permission (with admin consent), then disconnect and
            reconnect your Microsoft account.
          </div>
        )}
      </div>
    </>
  );
};

export default TeamsPublishModal;
