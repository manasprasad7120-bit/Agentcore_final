import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Plug, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  useGetMcpApprovalConfig,
  useProbeMcpApproval,
} from "@/controllers/API/queries/approvals";
import { useAnalyzeMCPRisk } from "@/controllers/API/queries/mcp/use-analyze-mcp-risk";
import RiskAssessmentPanel from "@/components/RiskAssessmentPanel";
import HighRiskConfirmDialog from "@/components/HighRiskConfirmDialog";
import type {
  McpProbeResponse,
  McpRiskAnalysisResponse,
  McpRiskFinding,
} from "@/types/mcp";

interface McpConfigModalProps {
  open: boolean;
  approvalId: string | null;
  setOpen: (open: boolean) => void;
}

export default function McpConfigModal({
  open,
  approvalId,
  setOpen,
}: McpConfigModalProps) {
  const { data, isLoading } = useGetMcpApprovalConfig(
    { approval_id: approvalId || "" },
    { enabled: open && !!approvalId },
  );
  const [environmentLabel, setEnvironmentLabel] = useState("");
  const [visibilityLabel, setVisibilityLabel] = useState("");
  const [riskAnalysis, setRiskAnalysis] = useState<McpRiskAnalysisResponse | null>(null);
  const analyzeRiskMutation = useAnalyzeMCPRisk();
  const probeMutation = useProbeMcpApproval();
  const [probeResult, setProbeResult] = useState<McpProbeResponse | null>(null);
  const [pendingProbeAck, setPendingProbeAck] = useState<McpRiskFinding[] | null>(null);

  useEffect(() => {
    if (!data) return;
    const envs = (data.environments || []).map((env) => String(env).toLowerCase());
    if (envs.includes("uat") && envs.includes("prod")) {
      setEnvironmentLabel("UAT + PROD");
    } else if (envs.length > 0) {
      setEnvironmentLabel(envs[0].toUpperCase());
    } else {
      setEnvironmentLabel(String(data.deployment_env || "UAT").toUpperCase());
    }

    if (data.visibility === "public") {
      setVisibilityLabel(data.public_scope === "organization" ? "Organization" : "Department");
    } else {
      setVisibilityLabel("Private");
    }
  }, [data]);

  useEffect(() => {
    if (!data) {
      setRiskAnalysis(null);
      return;
    }
    const payload =
      data.mode === "stdio"
        ? {
            mode: "stdio" as const,
            command: data.command || undefined,
            args: data.args || undefined,
          }
        : { mode: "sse" as const, url: data.url || undefined };
    analyzeRiskMutation
      .mutateAsync(payload)
      .then((res) => setRiskAnalysis(res))
      .catch(() => setRiskAnalysis(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.id, data?.mode, data?.command, data?.url, JSON.stringify(data?.args)]);

  useEffect(() => {
    if (!open) {
      setProbeResult(null);
      setPendingProbeAck(null);
    }
  }, [open, approvalId]);

  const runProbeNow = async () => {
    if (!approvalId) return;
    setProbeResult(null);
    try {
      const res = await probeMutation.mutateAsync({ approval_id: approvalId });
      setProbeResult(res);
    } catch (e: any) {
      setProbeResult({ success: false, message: e?.message ?? "Probe failed" });
    }
  };

  const handleTestConnection = async () => {
    if (!approvalId) return;
    const highs = (riskAnalysis?.findings ?? []).filter((f) => f.severity === "high");
    if (highs.length > 0) {
      setPendingProbeAck(highs);
      return;
    }
    await runProbeNow();
  };

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-card shadow-lg">
        <div className="flex items-start justify-between border-b p-5">
          <div>
            <h2 className="text-lg font-semibold">MCP Review Details</h2>
            <p className="text-sm text-muted-foreground">Review MCP configuration before approval</p>
          </div>
          <button onClick={() => setOpen(false)} className="rounded-sm opacity-70 hover:opacity-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="max-h-[65vh] space-y-4 overflow-y-auto p-5">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading config...
            </div>
          ) : !data ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              Unable to load MCP review details for this approval.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Server Name</Label>
                  <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                    {data.server_name || "-"}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Transport</Label>
                  <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm uppercase">
                    {data.mode || "-"}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Environment</Label>
                  <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                    {environmentLabel || "-"}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Visibility</Label>
                  <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                    {visibilityLabel || "-"}
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                  {data.description || "-"}
                </div>
              </div>
              {data.mode === "sse" ? (
                <div className="space-y-2">
                  <Label>Endpoint URL</Label>
                  <div className="break-all rounded-md border bg-muted/30 px-3 py-2 text-sm">
                    {data.url || "-"}
                  </div>
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <Label>Command</Label>
                    <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                      {data.command || "-"}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>Arguments</Label>
                    <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
                      {(data.args || []).length > 0 ? (data.args || []).join(", ") : "-"}
                    </div>
                  </div>
                </>
              )}
              <div className="space-y-2">
                <Label>Risk Assessment</Label>
                <RiskAssessmentPanel
                  analysis={riskAnalysis}
                  isLoading={analyzeRiskMutation.isPending && !riskAnalysis}
                  emptyMessage="Risk advisor could not analyse this configuration."
                />
                {probeResult && (
                  <div
                    className={`mt-2 flex items-start gap-2 rounded-md border p-3 text-sm ${
                      probeResult.success
                        ? "border-green-300 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300"
                        : "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300"
                    }`}
                  >
                    {probeResult.success ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
                    ) : (
                      <XCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">
                        {probeResult.success
                          ? `Connected - ${probeResult.tools_count ?? 0} tool(s) discovered`
                          : "Connection failed"}
                      </div>
                      {probeResult.message && (
                        <div className="mt-1 text-xs opacity-90">{probeResult.message}</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 border-t p-5">
          {data?.approval_status === "pending" ? (
            <Button
              variant="outline"
              onClick={handleTestConnection}
              disabled={!data || probeMutation.isPending}
            >
              {probeMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Testing...
                </>
              ) : (
                <>
                  <Plug className="mr-2 h-4 w-4" />
                  Test Connection
                </>
              )}
            </Button>
          ) : (
            <span />
          )}
          <Button variant="outline" onClick={() => setOpen(false)}>
            Close
          </Button>
        </div>
      </div>
      <HighRiskConfirmDialog
        open={!!pendingProbeAck}
        highFindings={pendingProbeAck ?? []}
        actionLabel="Test Connection"
        onCancel={() => setPendingProbeAck(null)}
        onConfirm={() => {
          setPendingProbeAck(null);
          void runProbeNow();
        }}
      />
    </>
  );
}
