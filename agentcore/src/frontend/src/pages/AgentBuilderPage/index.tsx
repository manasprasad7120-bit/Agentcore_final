import { useContext, useEffect, useState } from "react";
import { useBlocker, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useGetAgent } from "@/controllers/API/queries/agents/use-get-agent";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { ENABLE_NEW_SIDEBAR } from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import { useIsMobile } from "@/hooks/use-mobile";
import { SaveChangesModal } from "@/modals/saveChangesModal";
import useAlertStore from "@/stores/alertStore";
import { useTypesStore } from "@/stores/typesStore";
import { customStringify } from "@/utils/reactFlowUtils";
import useAgentStore from "../../stores/agentStore";
import useAgentsManagerStore from "../../stores/agentsManagerStore";
import { useTranslation } from "react-i18next";
import { AuthContext } from "@/contexts/authContext";
import VersionSavePrompt from "@/components/core/agentToolbarComponent/components/version-save-prompt";
import CopyAgentDialog from "@/components/agents/copy-agent-dialog";
import {
  AgentSearchProvider,
  AgentSidebarComponent,
} from "./components/agentSidebarComponent";
import Page from "./components/PageComponent";

export default function AgentBuilderPage({ view }: { view?: boolean }): JSX.Element {
  const types = useTypesStore((state) => state.types);

  useGetTypes({
    enabled: Object.keys(types).length <= 0,
  });
  const { t } = useTranslation();
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const currentAgent = useAgentStore((state) => state.currentAgent);
  const currentSavedAgent = useAgentsManagerStore((state) => state.currentAgent);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const [isLoading, setIsLoading] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);

  const isBuilding = useAgentStore((state) => state.isBuilding);
  const setOnAgentBuilderPage = useAgentStore((state) => state.setOnAgentBuilderPage);
  const stopBuilding = useAgentStore((state) => state.stopBuilding);
  const { id, folderId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useCustomNavigate();
  const saveAgent = useSaveAgent();
  const { userData, role, permissions } = useContext(AuthContext);
  const currentUserId = String(userData?.id ?? "");
  const normalizedRole = String(role ?? "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const isAdminRole = ["root", "super_admin", "department_admin"].includes(
    normalizedRole,
  );
  const canCopy = permissions?.includes("copy_agents");
  const requestedReadOnlyMode = view || searchParams.get("readonly") === "1";
  const forceReadOnlyByOwnership =
    !!folderId &&
    isAdminRole &&
    !!currentAgent &&
    (!!currentAgent.user_id ? String(currentAgent.user_id) !== currentUserId : true);
  const isReadOnlyMode = requestedReadOnlyMode || forceReadOnlyByOwnership;

  useEffect(() => {
    // Wait until the loaded agent actually matches the URL id. Otherwise we
    // would react to stale ownership data from the previously-viewed agent
    // (e.g. right after copying someone else's agent into our own project,
    // currentAgent is briefly the source agent and we'd pin ?readonly=1
    // onto the new agent's URL by mistake — leaving the new agent locked
    // in read-only with the Copy button still showing).
    if (!currentAgent || String(currentAgent.id) !== String(id)) return;
    const shouldBeReadOnly = forceReadOnlyByOwnership || Boolean(view);
    const hasParam = searchParams.get("readonly") === "1";
    if (shouldBeReadOnly && !hasParam) {
      const next = new URLSearchParams(searchParams);
      next.set("readonly", "1");
      setSearchParams(next, { replace: true });
    } else if (!shouldBeReadOnly && hasParam) {
      const next = new URLSearchParams(searchParams);
      next.delete("readonly");
      setSearchParams(next, { replace: true });
    }
  }, [currentAgent, id, forceReadOnlyByOwnership, view, searchParams, setSearchParams]);

  const changesNotSaved =
    !isReadOnlyMode &&
    customStringify(currentAgent) !== customStringify(currentSavedAgent) &&
    (currentAgent?.data?.nodes?.length ?? 0) > 0;

  const blocker = useBlocker(!isReadOnlyMode && (changesNotSaved || isBuilding));

  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const updatedAt = currentSavedAgent?.updated_at;
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const { mutateAsync: getAgent } = useGetAgent();

  const handleSave = () => {
    let done = false;
    const tryProceed = () => {
      if (done || blocker.state !== "blocked") return;
      done = true;
      blocker.proceed!();
      setSuccessData({ title: t("Agent saved successfully!") });
    };

    const timeoutId = setTimeout(tryProceed, 1200);

    saveAgent().then(() => {
      clearTimeout(timeoutId);
      tryProceed();
    });
  };

  const handleExit = () => {
    if (isBuilding) {
      // Do nothing, let the blocker handle it
    } else if (changesNotSaved) {
      if (blocker.state === "blocked") blocker.proceed!();
    } else {
      navigate("/all");
    }
  };

  useEffect(() => {
    if (isReadOnlyMode) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (changesNotSaved || isBuilding) {
        event.preventDefault();
        event.returnValue = ""; // Required for Chrome
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [changesNotSaved, isBuilding, isReadOnlyMode]);

  const getAgentToAddToCanvas = async (agentId: string) => {
    try {
      const agent = await getAgent({ id: agentId });
      const shouldForceReadOnlyForFetchedAgent =
        !!folderId &&
        isAdminRole &&
        (!!agent?.user_id ? String(agent.user_id) !== currentUserId : true);
      if (!requestedReadOnlyMode && !shouldForceReadOnlyForFetchedAgent) {
        await api.post(`${getURL("AGENTS")}/${agentId}/session/acquire`);
      }
      setCurrentAgent(agent);
    } catch (error: any) {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      setErrorData({
        title: status === 423 ? "Agent is currently locked" : "Unable to open agent",
        list: [typeof detail === "string" ? detail : "Please try again later."],
      });
      navigate("/all");
    }
  };

  // Set agent tab id
  useEffect(() => {
    const awaitGetTypes = async () => {
      if (!id || Object.keys(types).length === 0) {
        return;
      }

      // Route id is the source of truth. If store has stale state, reload.
      if (currentAgentId !== id || !currentAgent) {
        await getAgentToAddToCanvas(id);
      }
    };
    awaitGetTypes();
  }, [id, currentAgentId, currentAgent, types, isReadOnlyMode]);

  useEffect(() => {
    setOnAgentBuilderPage(true);

    return () => {
      setOnAgentBuilderPage(false);
      console.warn("unmounting");
      setCurrentAgent(undefined);
    };
  }, [id]);

  useEffect(() => {
    if (
      !isReadOnlyMode &&
      blocker.state === "blocked" &&
      autoSaving &&
      changesNotSaved &&
      !isBuilding
    ) {
      handleSave();
    }
  }, [blocker.state, isBuilding, autoSaving, changesNotSaved, isReadOnlyMode]);

  useEffect(() => {
    if (!isReadOnlyMode && blocker.state === "blocked") {
      if (isBuilding) {
        stopBuilding();
      } else if (!changesNotSaved) {
        if (blocker.state === "blocked") blocker.proceed!();
      }
    }
  }, [blocker.state, isBuilding, stopBuilding, changesNotSaved, isReadOnlyMode]);

  useEffect(() => {
    if (!id || !currentAgent || isReadOnlyMode) return;

    const heartbeat = setInterval(() => {
      api.post(`${getURL("AGENTS")}/${id}/session/acquire`).catch(() => {
        // Keep UX non-disruptive; hard failures are handled on explicit open.
      });
    }, 60_000);

    const release = () => {
      api.post(`${getURL("AGENTS")}/${id}/session/release`).catch(() => {
        // Best-effort release.
      });
    };

    window.addEventListener("beforeunload", release);

    return () => {
      clearInterval(heartbeat);
      window.removeEventListener("beforeunload", release);
      release();
    };
  }, [id, currentAgent, isReadOnlyMode]);

  const isMobile = useIsMobile();
  const handleBackToProject = () => {
    if (folderId) {
      navigate(`/agents/folder/${folderId}`);
      return;
    }
    navigate("/agents");
  };

  return (
    <>
      <VersionSavePrompt />
      <div className="agent-page-positioning">
        {currentAgent && (
          <div className="flex h-full overflow-hidden">
            {isReadOnlyMode ? (
              <SidebarProvider
                width="17.5rem"
                defaultOpen={!isMobile}
                segmentedSidebar={ENABLE_NEW_SIDEBAR}
              >
                <AgentSearchProvider>
                  <AgentSidebarComponent isLoading={isLoading} readOnly />
                  <main className="relative flex w-full overflow-hidden">
                    <div className="flex h-full w-full flex-col overflow-hidden">
                      <Button
                        variant="outline"
                        size="sm"
                        className="absolute left-4 top-12 z-40 gap-2 bg-background shadow-lg"
                        onClick={handleBackToProject}
                      >
                        <ArrowLeft className="h-4 w-4" />
                        Back
                      </Button>
                      <div className="h-full w-full">
                        <Page
                          view
                          enableViewportInteractions
                          showToolbarInView
                          toolbarReadOnly
                          setIsLoading={setIsLoading}
                        />
                      </div>
                    </div>
                  </main>
                </AgentSearchProvider>
              </SidebarProvider>
            ) : (
              <SidebarProvider
                width="17.5rem"
                defaultOpen={!isMobile}
                segmentedSidebar={ENABLE_NEW_SIDEBAR}
              >
                <AgentSearchProvider>
                  <AgentSidebarComponent isLoading={isLoading} />
                  <main className="flex w-full overflow-hidden">
                    <div className="h-full w-full">
                      <Page setIsLoading={setIsLoading} />
                    </div>
                  </main>
                </AgentSearchProvider>
              </SidebarProvider>
            )}
            {isReadOnlyMode && currentAgent && canCopy && (
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
                isReadOnlyMode && currentAgent
                  ? { type: "agent", agent: currentAgent }
                  : null
              }
              onSuccess={(agentId, projectId) =>
                navigate(`/agent/${agentId}/folder/${projectId}`)
              }
            />
          </div>
        )}
      </div>
      {!isReadOnlyMode && blocker.state === "blocked" && (
        <>
          {!isBuilding && currentSavedAgent && (
            <SaveChangesModal
              onSave={handleSave}
              onCancel={() => blocker.reset?.()}
              onProceed={handleExit}
              agentName={t(currentSavedAgent.name)}
              lastSaved={
                updatedAt
                  ? new Date(updatedAt).toLocaleString("en-US", {
                      hour: "numeric",
                      minute: "numeric",
                      second: "numeric",
                      month: "numeric",
                      day: "numeric",
                    })
                  : undefined
              }
              autoSave={autoSaving}
            />
          )}
        </>
      )}
    </>
  );
}
