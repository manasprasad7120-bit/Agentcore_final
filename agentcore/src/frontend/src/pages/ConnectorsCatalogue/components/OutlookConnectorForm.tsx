/**
 * Outlook-specific form fields for the Connector Catalogue modal.
 * Extracted into its own component to minimize merge conflicts
 * with the main ConnectorsCatalogue/index.tsx.
 */

import { Eye, EyeOff, Trash2, Loader2, RefreshCw } from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/controllers/API/api";

interface OutlookFormFields {
  outlook_tenant_id: string;
  outlook_client_id: string;
  outlook_client_secret: string;
}

interface LinkedAccount {
  email: string;
  display_name: string;
  linked_at: string;
  /**
   * Microsoft Graph scopes the user actually consented to for this mailbox.
   * Used to render a "Read-only" / "Read+Send" / "Full" capability badge
   * so users see up-front what this mailbox can do, rather than discovering
   * later when a write operation fails. Empty / missing = legacy account
   * linked before the backend started persisting this field — treated as
   * "Unknown" with a permissive fallback.
   */
  granted_scopes?: string[];
}

/** Derive a short capability label from the granted_scopes list. */
function capabilityFor(scopes: string[] | undefined): {
  label: string;
  tone: "ok" | "warn" | "muted";
  detail: string;
} {
  if (!scopes || scopes.length === 0) {
    return {
      label: "Unknown",
      tone: "muted",
      detail:
        "This mailbox was linked before scope discovery was enabled. Re-link to populate granted permissions.",
    };
  }
  const hasRead = scopes.includes("Mail.Read");
  const hasReadWrite = scopes.includes("Mail.ReadWrite");
  const hasSend = scopes.includes("Mail.Send");
  if (hasRead && hasReadWrite && hasSend) {
    return {
      label: "Full",
      tone: "ok",
      detail: "Read, send, reply, and mark-as-read all available.",
    };
  }
  if (hasRead && hasSend) {
    return {
      label: "Read + Send",
      tone: "ok",
      detail: "Read and send/reply available. Mark-as-read disabled (no Mail.ReadWrite).",
    };
  }
  if (hasRead && hasReadWrite) {
    return {
      label: "Read + Modify",
      tone: "warn",
      detail: "Read and mark-as-read available. Send/reply disabled (no Mail.Send).",
    };
  }
  if (hasRead) {
    return {
      label: "Read-only",
      tone: "warn",
      detail:
        "Reading inbox + triggers work. Send/reply/mark-as-read disabled — ask your admin to grant Mail.Send and/or Mail.ReadWrite.",
    };
  }
  return {
    label: "Limited",
    tone: "warn",
    detail: `Granted scopes: ${scopes.join(", ")}. Mailbox features may not work — ask your admin to grant Mail.Read.`,
  };
}

interface Props {
  form: OutlookFormFields;
  onChange: (field: string, value: string) => void;
  isEditing: boolean;
  connectorId?: string;
}

export default function OutlookConnectorForm({ form, onChange, isEditing, connectorId }: Props) {
  const { t } = useTranslation();
  const [showSecret, setShowSecret] = useState(false);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [removingEmail, setRemovingEmail] = useState<string | null>(null);
  const [unlinkError, setUnlinkError] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    if (!connectorId) return;
    setLoadingAccounts(true);
    try {
      const res = await api.get(`/api/outlook/${connectorId}/accounts`);
      setAccounts(res.data ?? []);
    } catch {
      setAccounts([]);
    } finally {
      setLoadingAccounts(false);
    }
  }, [connectorId]);

  useEffect(() => {
    if (isEditing && connectorId) {
      fetchAccounts();
    }
  }, [isEditing, connectorId, fetchAccounts]);

  const handleRemoveAccount = async (email: string) => {
    if (!connectorId) return;
    setRemovingEmail(email);
    setUnlinkError(null);
    try {
      await api.delete(`/api/outlook/${connectorId}/accounts/${encodeURIComponent(email)}`);
      setAccounts((prev) => prev.filter((a) => a.email !== email));
    } catch (err: unknown) {
      // Surface the failure so the user knows to retry / fix something,
      // instead of leaving them confused with a still-listed mailbox.
      const detail =
        (err as { response?: { data?: { detail?: string } }; message?: string })
          ?.response?.data?.detail ??
        (err as { message?: string })?.message ??
        "Unknown error";
      setUnlinkError(`Failed to unlink ${email}: ${detail}`);
    } finally {
      setRemovingEmail(null);
    }
  };

  return (
    <>
      <div>
        <label className="mb-1.5 block text-sm font-medium">{t("Azure Tenant ID")}</label>
        <input
          value={form.outlook_tenant_id}
          onChange={(e) => onChange("outlook_tenant_id", e.target.value)}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-sm font-medium">{t("Client ID (App Registration)")}</label>
        <input
          value={form.outlook_client_id}
          onChange={(e) => onChange("outlook_client_id", e.target.value)}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-sm font-medium">
          {t("Client Secret")}{" "}
          {isEditing && (
            <span className="text-xs text-muted-foreground">{t("(leave blank to keep current)")}</span>
          )}
        </label>
        <div className="relative">
          <input
            type={showSecret ? "text" : "password"}
            value={form.outlook_client_secret}
            onChange={(e) => onChange("outlook_client_secret", e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 pr-10 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            placeholder={isEditing ? t("(unchanged)") : t("client-secret")}
          />
          <button
            type="button"
            onClick={() => setShowSecret(!showSecret)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("After saving, use the OAuth flow to link individual mailboxes to this connector.")}
      </p>

      {isEditing && connectorId && (
        <div className="mt-4 rounded-lg border border-border p-4">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-medium">{t("Linked Mailboxes")}</h4>
            <button
              type="button"
              onClick={fetchAccounts}
              disabled={loadingAccounts}
              className="text-muted-foreground hover:text-foreground disabled:opacity-50"
              title={t("Refresh accounts")}
            >
              <RefreshCw className={`h-4 w-4 ${loadingAccounts ? "animate-spin" : ""}`} />
            </button>
          </div>

          {loadingAccounts && accounts.length === 0 ? (
            <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("Loading accounts...")}
            </div>
          ) : accounts.length === 0 ? (
            <p className="py-3 text-sm text-muted-foreground">
              {t("No mailboxes linked yet. Use the OAuth flow to link one.")}
            </p>
          ) : (
            <ul className="space-y-2">
              {accounts.map((acct) => {
                const cap = capabilityFor(acct.granted_scopes);
                const toneClass =
                  cap.tone === "ok"
                    ? "border-green-200 bg-green-50 text-green-800"
                    : cap.tone === "warn"
                      ? "border-amber-200 bg-amber-50 text-amber-800"
                      : "border-border bg-muted text-muted-foreground";
                return (
                  <li
                    key={acct.email}
                    className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium">{acct.email}</p>
                        <span
                          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${toneClass}`}
                          title={cap.detail}
                        >
                          {cap.label}
                        </span>
                      </div>
                      {acct.display_name && (
                        <p className="truncate text-xs text-muted-foreground">{acct.display_name}</p>
                      )}
                      {cap.tone === "warn" && (
                        <p className="mt-1 text-[11px] leading-snug text-amber-700">{cap.detail}</p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRemoveAccount(acct.email)}
                      disabled={removingEmail === acct.email}
                      className="ml-2 shrink-0 text-muted-foreground hover:text-destructive disabled:opacity-50"
                      title={t("Remove {{email}}", { email: acct.email })}
                    >
                      {removingEmail === acct.email ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {unlinkError && (
            <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
              {unlinkError}
            </div>
          )}
        </div>
      )}
    </>
  );
}
