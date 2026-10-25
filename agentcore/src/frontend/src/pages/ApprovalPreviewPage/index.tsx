import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { AgentType } from "@/types/agent";
import { AuthContext } from "@/contexts/authContext";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { useGetApprovalPreview } from "@/controllers/API/queries/approvals";
import CopyAgentDialog from "@/components/agents/copy-agent-dialog";
import CustomLoader from "@/customization/components/custom-loader";
import { ENABLE_NEW_SIDEBAR } from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useIsMobile } from "@/hooks/use-mobile";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import useAgentStore from "@/stores/agentStore";
import { useTypesStore } from "@/stores/typesStore";
import { processAgents } from "@/utils/reactFlowUtils";
import {
  AgentSearchProvider,
  AgentSidebarComponent,
} from "../AgentBuilderPage/components/agentSidebarComponent";
import Page from "../AgentBuilderPage/components/PageComponent";

export default function ApprovalPreviewPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useCustomNavigate();
  const { agentId } = useParams();
  const isMobile = useIsMobile();
  const [canvasLoading, setCanvasLoading] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const { permissions } = useContext(AuthContext);
  const canCopy = permissions?.includes("copy_agents");
  const types = useTypesStore((state) => state.types);
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const currentAgent = useAgentStore((state) => state.currentAgent);

  useGetTypes({
    enabled: Object.keys(types).length <= 0,
  });

  const {
    data: previewData,
    isLoading,
    isError,
  } = useGetApprovalPreview(
    { agent_id: agentId || "" },
    { enabled: !!agentId },
  );

  useEffect(() => {
    const snapshot = previewData?.snapshot as any;
    const isFlowSnapshot = Array.isArray(snapshot?.nodes);
    if (previewData && isFlowSnapshot) {
      const flowAgent: AgentType = {
        id: `approval-preview-${previewData.id}`,
        name: previewData.title,
        description: "",
        data: snapshot,
        public: true,
        locked: true,
      };
      const { agents } = processAgents([flowAgent]);
      setCurrentAgent(agents[0]);
    }
    return () => {
      setCurrentAgent(undefined);
    };
  }, [previewData, setCurrentAgent]);

  const snapshot = previewData?.snapshot as any;
  const isFlowSnapshot = Array.isArray(snapshot?.nodes);

  if (isFlowSnapshot && previewData && !isLoading) {
    return (
      <div className="flex h-full w-full flex-col overflow-hidden">
        <SidebarProvider
          width="17.5rem"
          defaultOpen={!isMobile}
          segmentedSidebar={ENABLE_NEW_SIDEBAR}
        >
          <AgentSearchProvider>
            <AgentSidebarComponent isLoading={canvasLoading} readOnly />
            <main className="flex w-full overflow-hidden">
              <div className="flex h-full w-full flex-col overflow-hidden">
                <div className="flex items-center gap-2 border-b bg-background px-3 py-2">
                  <Button variant="outline" size="sm" onClick={() => navigate("/approval")}>
                    {t("Back To Approval")}
                  </Button>
                  <span className="truncate text-sm text-muted-foreground">
                    {previewData?.title || t("Review Details")}
                  </span>
                </div>
                <div className="h-full w-full">
                  <Page
                    view
                    enableViewportInteractions
                    showToolbarInView
                    toolbarReadOnly
                    setIsLoading={setCanvasLoading}
                  />
                </div>
              </div>
            </main>
          </AgentSearchProvider>
        </SidebarProvider>
        {canCopy && currentAgent && (
          <Button
            className="fixed bottom-6 right-6 z-40 gap-2 shadow-lg"
            onClick={() => setCloneOpen(true)}
          >
            <Copy className="h-4 w-4" />
            {t("Copy")}
          </Button>
        )}
        <CopyAgentDialog
          open={cloneOpen}
          onOpenChange={setCloneOpen}
          source={
            currentAgent
              ? { type: "agent", agent: currentAgent }
              : null
          }
          onSuccess={(agentId, projectId) =>
            navigate(`/agent/${agentId}/folder/${projectId}`)
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">
            {previewData?.title || t("Review Details")}
          </h1>
          <p className="text-xs text-muted-foreground">
            {t("Submitted request details")}
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/approval")}>
          {t("Back to Approval")}
        </Button>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-auto">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : !previewData || isError ? (
          <div className="flex h-full w-full items-center justify-center p-6">
            <div className="rounded-lg border border-border bg-card p-6 text-center">
              <p className="text-sm text-muted-foreground">
                {t("Unable to load review preview for this approval.")}
              </p>
            </div>
          </div>
        ) : snapshot?.model_id ? (
          /* Model approval preview - simple request details */
          <div className="p-6">
            <div className="mx-auto max-w-2xl space-y-6">
              {/* Model Name & Description */}
              <div className="rounded-lg border border-border bg-card p-4">
                <h2 className="text-lg font-semibold">{snapshot.display_name}</h2>
                {snapshot.description && (
                  <p className="mt-2 text-sm text-muted-foreground">{snapshot.description}</p>
                )}
              </div>

              {/* Requested Details */}
              <div className="space-y-4 rounded-lg border border-border bg-card p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("Requested Details")}
                </h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Provider")}</div>
                    <div className="font-medium capitalize">{snapshot.provider}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Model ID")}</div>
                    <div className="font-mono font-medium">{snapshot.model_name}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Type")}</div>
                    <div className="font-medium uppercase">{snapshot.model_type}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Requested Environment")}</div>
                    <div className="font-medium uppercase">
                      {(() => {
                        const envs = Array.isArray(snapshot.environments)
                          ? snapshot.environments.map((env: string) => String(env).toLowerCase())
                          : [];
                        if (envs.includes("uat") && envs.includes("prod")) return "UAT + PROD";
                        const env = snapshot.target_environment || snapshot.environment;
                        return env === "test" ? "UAT" : env?.toUpperCase();
                      })()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Requested Visibility")}</div>
                    <div className="font-medium capitalize">
                      {snapshot.visibility_requested || snapshot.visibility_scope}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Requests per minute")}</div>
                    <div className="font-medium">
                      {snapshot.rate_limit_rpm
                        ? snapshot.rate_limit_rpm
                        : t("Unlimited")}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Tokens per minute")}</div>
                    <div className="font-medium">
                      {snapshot.rate_limit_tpm
                        ? snapshot.rate_limit_tpm
                        : t("Unlimited")}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Status")}</div>
                    <div className="font-medium capitalize">{snapshot.approval_status}</div>
                  </div>
                </div>
              </div>

              {/* Request Information (charge code, project, reason) */}
              {snapshot.provider_config?.request_meta && (
                <div className="space-y-4 rounded-lg border border-border bg-card p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Request Information")}
                  </h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    {snapshot.provider_config.request_meta.charge_code && (
                      <div>
                        <div className="text-xs text-muted-foreground">{t("Charge Code")}</div>
                        <div className="font-medium">{snapshot.provider_config.request_meta.charge_code}</div>
                      </div>
                    )}
                    {snapshot.provider_config.request_meta.project_name && (
                      <div>
                        <div className="text-xs text-muted-foreground">{t("Project Name")}</div>
                        <div className="font-medium">{snapshot.provider_config.request_meta.project_name}</div>
                      </div>
                    )}
                  </div>
                  {snapshot.provider_config.request_meta.reason && (
                    <div>
                      <div className="text-xs text-muted-foreground">{t("Reason")}</div>
                      <div className="mt-1 text-sm">{snapshot.provider_config.request_meta.reason}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Generic fallback for MCP and other non-flow snapshots */
          <div className="p-6">
            <div className="rounded-lg border border-border bg-card p-4">
              <pre className="whitespace-pre-wrap break-words text-sm text-foreground">
                {JSON.stringify(previewData.snapshot, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
