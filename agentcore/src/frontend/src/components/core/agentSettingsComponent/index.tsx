import * as Form from "@radix-ui/react-form";
import { cloneDeep } from "lodash";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useGetPublishStatus } from "@/controllers/API/queries/agents/use-get-publish-status";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import useAlertStore from "@/stores/alertStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { AgentType } from "@/types/agent";
import EditAgentSettings from "../editAgentSettingsComponent";

type AgentSettingsComponentProps = {
  agentData?: AgentType;
  close: () => void;
  open: boolean;
};

const updateAgentWithFormValues = (
  baseAgent: AgentType,
  newName: string,
  newDescription: string,
  newLocked: boolean,
  newTags?: string[],
): AgentType => {
  const newAgent = cloneDeep(baseAgent);
  newAgent.name = newName;
  newAgent.description = newDescription;
  newAgent.locked = newLocked;
  if (newTags !== undefined) newAgent.tags = newTags;
  return newAgent;
};

const buildInvalidNameList = (
  allAgents: AgentType[] | undefined,
  currentAgentName: string | undefined,
): string[] => {
  if (!allAgents) return [];
  const names = allAgents.map((f) => f?.name ?? "");
  return names.filter((n) => n !== (currentAgentName ?? ""));
};

const isSaveDisabled = (
  agent: AgentType | undefined,
  invalidNameList: string[],
  name: string,
  description: string,
  locked: boolean,
  tags?: string[],
): boolean => {
  if (!agent) return true;
  const isNameChangedAndValid =
    !invalidNameList.includes(name) && agent.name !== name;
  const isDescriptionChanged = agent.description !== description;
  const isLockedChanged = agent.locked !== locked;
  const isTagsChanged = JSON.stringify(agent.tags ?? []) !== JSON.stringify(tags ?? []);
  return !(isNameChangedAndValid || isDescriptionChanged || isLockedChanged || isTagsChanged);
};

const AgentSettingsComponent = ({
  agentData,
  close,
  open,
}: AgentSettingsComponentProps): JSX.Element => {
  const saveAgent = useSaveAgent();
  const currentAgent = useAgentStore((state) =>
    agentData ? undefined : state.currentAgent,
  );
  const setCurrentAgent = useAgentStore((state) => state.setCurrentAgent);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const agents = useAgentsManagerStore((state) => state.agents);
  const agent = agentData ?? currentAgent;
  const { data: publishStatus } = useGetPublishStatus(
    { agent_id: agent?.id ?? "" },
    { enabled: open && !!agent?.id },
  );
  const [name, setName] = useState(agent?.name ?? "");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [locked, setLocked] = useState<boolean>(agent?.locked ?? false);
  const [tags, setTags] = useState<string[]>(agent?.tags ?? []);
  const [isSaving, setIsSaving] = useState(false);
  const [disableSave, setDisableSave] = useState(true);
  const nameLockedAfterFirstPublish = Boolean(publishStatus?.uat?.agent_name || publishStatus?.prod?.agent_name);
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    setName(agent?.name ?? "");
    setDescription(agent?.description ?? "");
    setLocked(agent?.locked ?? false);
    setTags(agent?.tags ?? []);
  }, [agent?.name, agent?.description, agent?.endpoint_name, open]);

  function handleSubmit(event?: React.FormEvent<HTMLFormElement>): void {
    if (event) event.preventDefault();
    setIsSaving(true);
    if (!agent) return;
    const newAgent = updateAgentWithFormValues(agent, name, description, locked, tags);

    if (autoSaving) {
      saveAgent(newAgent)
        ?.then(() => {
          setIsSaving(false);
          setSuccessData({ title: "Changes saved successfully", link: agent?.id ? `/agent/${agent.id}` : undefined });
          close();
        })
        .catch(() => {
          setIsSaving(false);
        });
    } else {
      setCurrentAgent(newAgent);
      setIsSaving(false);
      close();
    }
  }

  const submitForm = () => {
    formRef.current?.requestSubmit();
  };

  const [nameLists, setNameList] = useState<string[]>([]);

  useEffect(() => {
    setNameList(buildInvalidNameList(agents, agent?.name));
  }, [agents]);

  useEffect(() => {
    setDisableSave(isSaveDisabled(agent, nameLists, name, description, locked, tags));
  }, [nameLists, agent, description, name, locked, tags]);
  return (
    <Form.Root onSubmit={handleSubmit} ref={formRef}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <EditAgentSettings
            invalidNameList={nameLists}
            name={name}
            description={description}
            setName={setName}
            setDescription={setDescription}
            submitForm={submitForm}
            locked={locked}
            setLocked={setLocked}
            nameDisabled={nameLockedAfterFirstPublish}
            tags={tags}
            setTags={setTags}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            data-testid="cancel-agent-settings"
            type="button"
            onClick={() => close()}
          >
            Cancel
          </Button>
          <Form.Submit asChild>
            <Button
              variant="default"
              size="sm"
              data-testid="save-agent-settings"
              loading={isSaving}
              disabled={disableSave}
            >
              Save
            </Button>
          </Form.Submit>
        </div>
      </div>
    </Form.Root>
  );
};

export default AgentSettingsComponent;
