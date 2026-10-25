import IconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useGetPublishVersions } from "@/controllers/API/queries/agents/use-get-publish-versions";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import useAlertStore from "@/stores/alertStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { AgentType, PublishedVersionSelection } from "@/types/agent";
import { useEffect, useMemo, useRef, useState } from "react";

const buildDraftSnapshot = (): AgentType | null => {
  const currentAgent = useAgentStore.getState().currentAgent;
  if (!currentAgent) {
    return null;
  }
  const nodes = useAgentStore.getState().nodes;
  const edges = useAgentStore.getState().edges;
  const reactFlowInstance = useAgentStore.getState().reactFlowInstance;
  return {
    ...currentAgent,
    data: {
      ...(currentAgent.data ?? {}),
      nodes,
      edges,
      viewport: reactFlowInstance?.getViewport() ?? { zoom: 1, x: 0, y: 0 },
    },
  };
};

const formatPublishedVersionLabel = (record: {
  agent_name: string;
  environment: "uat" | "prod";
  version_number: string;
}) => {
  const agentName = String(record.agent_name || "Unnamed agent").trim();
  return `${agentName} - ${record.version_number} (${record.environment.toUpperCase()})`;
};

const PublishVersionDropdown = (): JSX.Element | null => {
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const currentAgent = useAgentsManagerStore((state) => state.currentAgent);
  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const activePublishedVersion = useAgentStore((state) => state.activePublishedVersion);
  const setActivePublishedVersion = useAgentStore(
    (state) => state.setActivePublishedVersion,
  );
  const [loadingVersionId, setLoadingVersionId] = useState<string | null>(null);
  const draftAgentRef = useRef<AgentType | null>(null);

  const { data: uatVersions } = useGetPublishVersions(
    { agent_id: currentAgentId, env: "uat" },
    { enabled: !!currentAgentId },
  );
  const { data: prodVersions } = useGetPublishVersions(
    { agent_id: currentAgentId, env: "prod" },
    { enabled: !!currentAgentId },
  );

  const allVersions = useMemo(() => {
    const combined = [...(uatVersions ?? []), ...(prodVersions ?? [])];
    return combined.sort(
      (a, b) =>
        new Date(b.published_at).getTime() - new Date(a.published_at).getTime(),
    );
  }, [uatVersions, prodVersions]);

  useEffect(() => {
    setActivePublishedVersion(null);
    draftAgentRef.current = null;
  }, [currentAgentId, setActivePublishedVersion]);

  if (!currentAgentId || allVersions.length === 0) {
    return null;
  }

  const handleSelectDraft = () => {
    const draftAgent = draftAgentRef.current ?? buildDraftSnapshot();
    if (draftAgent) {
      setCurrentAgent(draftAgent);
    }
    setActivePublishedVersion(null);
  };

  const handleSelectVersion = async (record: {
    id: string;
    version_number: string;
    agent_name: string;
    agent_description: string | null;
    environment: "uat" | "prod";
    visibility: "PUBLIC" | "PRIVATE";
  }) => {
    const draftSnapshot = buildDraftSnapshot();
    if (draftSnapshot) {
      draftAgentRef.current = draftSnapshot;
    }

    setLoadingVersionId(record.id);
    try {
      const response = await api.get(
        `${getURL("PUBLISH")}/${record.id}/snapshot`,
      );
      const snapshotPayload = response?.data ?? {};
      const snapshotData = snapshotPayload?.agent_snapshot ?? null;

      const agentForCanvas: AgentType = {
        id: String(snapshotPayload?.agent_id ?? currentAgentId),
        name: String(snapshotPayload?.agent_name ?? record.agent_name ?? "agent"),
        description: String(
          snapshotPayload?.agent_description ?? record.agent_description ?? "",
        ),
        data: snapshotData,
        endpoint_name: null,
        tags: [],
        is_component: false,
      };

      const selectedVersion: PublishedVersionSelection = {
        agentId: agentForCanvas.id,
        deployId: record.id,
        versionNumber: record.version_number,
        environment: record.environment,
        visibility: record.visibility,
      };

      setCurrentAgent(agentForCanvas);
      setActivePublishedVersion(selectedVersion);
    } catch (error: any) {
      setErrorData({
        title: "Failed to load published version",
        list: [
          error?.response?.data?.detail || error?.message || "Unknown error",
        ],
      });
    } finally {
      setLoadingVersionId(null);
    }
  };

  const activeRecord = activePublishedVersion
    ? allVersions.find((record) => record.id === activePublishedVersion.deployId) ??
      null
    : null;

  const activeLabel = activeRecord
    ? formatPublishedVersionLabel(activeRecord)
    : activePublishedVersion
      ? `${activePublishedVersion.versionNumber} (${activePublishedVersion.environment.toUpperCase()})`
      : "Draft";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="max-w-[140px] gap-1 px-2 sm:max-w-[170px] lg:max-w-[220px] xl:max-w-[340px]"
          data-testid="publish-version-dropdown"
          title={activeLabel}
        >
          <span className="hidden text-xs text-muted-foreground xl:inline">Version</span>
          <span className="truncate font-medium">{activeLabel}</span>
          <IconComponent name="ChevronDown" className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[320px]">
        <DropdownMenuItem
          onClick={handleSelectDraft}
          disabled={!draftAgentRef.current && !currentAgent}
        >
          Draft (current)
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {allVersions.map((record) => (
          <DropdownMenuItem
            key={record.id}
            disabled={loadingVersionId === record.id}
            onClick={() => handleSelectVersion(record)}
            className="flex items-center justify-between gap-3"
          >
            <span className="truncate">
              {formatPublishedVersionLabel(record)}
            </span>
            {record.is_active ? "Active" : ""}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default PublishVersionDropdown;
