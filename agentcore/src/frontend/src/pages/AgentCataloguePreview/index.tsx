import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AuthContext } from "@/contexts/authContext";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { useGetRegistryPreview } from "@/controllers/API/queries/registry";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import CustomLoader from "@/customization/components/custom-loader";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useTypesStore } from "@/stores/typesStore";
import Page from "../AgentBuilderPage/components/PageComponent";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AgentSearchProvider, AgentSidebarComponent } from "../AgentBuilderPage/components/agentSidebarComponent";
import { ENABLE_NEW_SIDEBAR } from "@/customization/feature-flags";
import CopyAgentDialog from "@/components/agents/copy-agent-dialog";

export default function AgentCataloguePreviewPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useCustomNavigate();
  const { registryId } = useParams();
  const { permissions } = useContext(AuthContext);
  const [cloneOpen, setCloneOpen] = useState(false);
  const types = useTypesStore((state) => state.types);
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const canCopy = permissions?.includes("copy_agents");

  useGetTypes({
    enabled: Object.keys(types).length <= 0,
  });

  const { data: previewAgent, isLoading, isFetching } = useGetRegistryPreview(
    { registry_id: registryId || "" },
    { enabled: !!registryId },
  );

  useEffect(() => {
    if (previewAgent) {
      setCurrentAgent(previewAgent);
    }

    return () => {
      setCurrentAgent(undefined);
    };
  }, [previewAgent, setCurrentAgent]);

  const subtitle = useMemo(() => {
    if (!previewAgent?.data?.nodes?.length) {
      return t("No components available in this deployed snapshot.");
    }
    return t("{{count}} component(s)", { count: previewAgent.data.nodes.length });
  }, [previewAgent, t]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{previewAgent?.name || t("Agent Preview")}</h1>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <Button variant="outline" onClick={() => navigate("/agent-catalogue")}>
          {t("Back to Registry")}
        </Button>
      </div>
      <div className="h-full w-full">
        {isLoading || isFetching || !previewAgent ? (
          <div className="flex h-full w-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : (
          <SidebarProvider
            width="17.5rem"
            defaultOpen
            segmentedSidebar={ENABLE_NEW_SIDEBAR}
          >
            <AgentSearchProvider>
              <AgentSidebarComponent readOnly />
              <main className="flex w-full overflow-hidden">
                <div className="h-full w-full">
                  <Page
                    view
                    enableViewportInteractions
                    showToolbarInView
                    toolbarReadOnly
                    setIsLoading={() => undefined}
                  />
                </div>
              </main>
            </AgentSearchProvider>
          </SidebarProvider>
        )}
      </div>
      {canCopy && previewAgent && (
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
          registryId && previewAgent
            ? { type: "registry", registryId, title: previewAgent.name }
            : null
        }
        onSuccess={(agentId, projectId) =>
          navigate(`/agent/${agentId}/folder/${projectId}`)
        }
      />
    </div>
  );
}
