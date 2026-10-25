/**
 * SharePoint capability banner — surfaces what the connector's app reg can
 * actually do (read vs write) by calling /api/sharepoint/{id}/capabilities.
 *
 * The endpoint acquires an app-only token, decodes its JWT roles claim, and
 * runs a real list_drives() probe before reporting can_read / can_write so
 * users see the true capability state up front instead of discovering it
 * after a failed write.
 *
 * Rendering:
 *   - "Read-only" amber banner when can_read=true but can_write=false
 *   - "Full access" green banner when both true
 *   - "Probe failed" red banner with the underlying error
 *   - Loading spinner while the probe runs
 */

import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/controllers/API/api";

interface CapabilitiesResponse {
  connector_id: string;
  granted_roles: string[];
  token_acquired: boolean;
  can_read: boolean;
  can_write: boolean;
  read_probe_error?: string | null;
}

interface Props {
  connectorId: string | undefined;
}

export default function SharePointCapabilityBanner({ connectorId }: Props) {
  const [loading, setLoading] = useState(false);
  const [caps, setCaps] = useState<CapabilitiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!connectorId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCaps(null);
    (async () => {
      try {
        const res = await api.get<CapabilitiesResponse>(
          `/api/sharepoint/${connectorId}/capabilities`,
        );
        if (!cancelled) setCaps(res.data);
      } catch (err: unknown) {
        if (!cancelled) {
          const detail =
            (
              err as {
                response?: { data?: { detail?: string } };
                message?: string;
              }
            )?.response?.data?.detail ??
            (err as { message?: string })?.message ??
            "Unable to probe SharePoint capabilities.";
          setError(detail);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [connectorId]);

  if (!connectorId) return null;

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Probing SharePoint permissions…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
        <div className="flex items-start gap-2">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <strong>Capability probe failed.</strong> {error}
          </div>
        </div>
      </div>
    );
  }

  if (!caps) return null;

  // Probe succeeded — render based on actual capabilities.
  const roles = caps.granted_roles ?? [];
  const rolesText = roles.length > 0 ? roles.join(", ") : "(none decoded)";

  if (!caps.token_acquired) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <strong>Could not acquire an app-only token.</strong> Verify
            tenant ID, client ID, and client secret. {caps.read_probe_error}
          </div>
        </div>
      </div>
    );
  }

  if (!caps.can_read) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
        <div className="flex items-start gap-2">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <strong>No read access.</strong>{" "}
            {caps.read_probe_error ??
              "Token acquired but Graph rejected list_drives. Ask your admin to grant Sites.Read.All (or Sites.Selected on this site) with admin consent."}
            <br />
            <span className="text-[11px] opacity-80">
              Granted roles: {rolesText}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (caps.can_read && !caps.can_write) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <strong>Read-only connector.</strong> Listing libraries, browsing
            folders, downloading files (RAG ingestion), and search all work.
            Upload and create-folder are blocked because{" "}
            <code>Sites.ReadWrite.All</code> is not granted on the app
            registration. Ask your admin to grant it (with admin consent) if
            you need writes — then reload this page.
            <br />
            <span className="text-[11px] opacity-80">
              Granted roles: {rolesText}
            </span>
          </div>
        </div>
      </div>
    );
  }

  // Both can_read and can_write
  return (
    <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800">
      <div className="flex items-start gap-2">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <strong>Full access.</strong> All SharePoint operations available
          (read, search, upload, create folder).
          <br />
          <span className="text-[11px] opacity-80">
            Granted roles: {rolesText}
          </span>
        </div>
      </div>
    </div>
  );
}
