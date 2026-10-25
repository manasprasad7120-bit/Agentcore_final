import useAgentsManagerStore from "@/stores/agentsManagerStore";
import useAgentStore from "@/stores/agentStore";
import type { AgentType } from "@/types/agent";
import { useDebounce } from "../use-debounce";
import useSaveAgent from "./use-save-agent";

const useAutoSaveAgent = () => {
  const saveAgent = useSaveAgent();
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const autoSavingInterval = useAgentsManagerStore(
    (state) => state.autoSavingInterval,
  );

  const autoSaveAgent = useDebounce((agent?: AgentType) => {
    if (autoSaving) {
      const currentAgentId = useAgentsManagerStore.getState().currentAgentId;
      const autoSaveDisabled =
        useAgentsManagerStore.getState().autoSaveDisabledAgents?.[currentAgentId];
      if (autoSaveDisabled) {
        return;
      }
      const activePublishedVersion = useAgentStore.getState().activePublishedVersion;
      const existingPrompt = useAgentsManagerStore.getState().versionSavePrompt;
      if (activePublishedVersion) {
        if (!existingPrompt) {
          useAgentsManagerStore.getState().openVersionSavePrompt({
            source: "auto",
            version: activePublishedVersion,
          });
        }
        return;
      }
      saveAgent(agent);
    }
  }, autoSavingInterval);

  return autoSaveAgent;
};

export default useAutoSaveAgent;
