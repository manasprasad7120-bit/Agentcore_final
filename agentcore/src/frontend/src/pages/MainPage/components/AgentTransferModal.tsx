import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePostAddAgent } from "@/controllers/API/queries/agents/use-post-add-agent";
import { usePatchUpdateAgent } from "@/controllers/API/queries/agents/use-patch-update-agent";
import { usePostFolders } from "@/controllers/API/queries/folders/use-post-folders";
import BaseModal from "@/modals/baseModal";
import useAlertStore from "@/stores/alertStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";
import type { AgentType } from "@/types/agent";
import { createNewAgent } from "@/utils/reactflowUtils";

type TransferMode = "move" | "copy";

type AgentTransferModalProps = {
  open: boolean;
  setOpen: (open: boolean) => void;
  mode: TransferMode;
  agent: AgentType;
  currentProjectId?: string;
  deploymentWarning?: boolean;
};

const CREATE_NEW_VALUE = "__create__";

const AgentTransferModal = ({
  open,
  setOpen,
  mode,
  agent,
  currentProjectId,
  deploymentWarning = false,
}: AgentTransferModalProps) => {
  const folders = useFolderStore((state) => state.folders);
  const { mutateAsync: postAddAgent } = usePostAddAgent();
  const { mutateAsync: patchAgent } = usePatchUpdateAgent();
  const { mutateAsync: postFolder } = usePostFolders();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setAgents = useAgentsManagerStore((state) => state.setAgents);
  const queryClient = useQueryClient();
  const [targetProjectId, setTargetProjectId] = useState("");
  const [creatingNewProject, setCreatingNewProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const availableProjects = useMemo(() => {
    const list = folders || [];
    if (!currentProjectId) {
      return list;
    }
    return list.filter((folder) => folder.id !== currentProjectId);
  }, [folders, currentProjectId]);

  const warningTitle =
    mode === "move" ? "Moving an agent to another project" : "Copy creates a new agent";
  const warningDescription =
    mode === "move"
      ? "The agent keeps the same ID and name; only its project changes. Links, runs, and references stay valid."
      : "This creates a new agent in the selected project. The copied agent will have a new agent ID and project ID. The original agent stays in its current project.";
  const deploymentDescription =
    deploymentWarning && mode === "copy"
      ? "This agent has a UAT/PROD version, so moving is disabled. Copying creates a new agent without affecting the deployed version."
      : "";

  useEffect(() => {
    if (open) {
      setTargetProjectId("");
      setCreatingNewProject(false);
      setNewProjectName("");
      setIsSubmitting(false);
    }
  }, [open, mode, agent.id]);

  const canSubmit =
    !isSubmitting &&
    (creatingNewProject
      ? newProjectName.trim().length > 0
      : !!targetProjectId);

  const submitLabel =
    mode === "move"
      ? creatingNewProject
        ? "Create & Move"
        : "Move Agent"
      : creatingNewProject
        ? "Create & Copy"
        : "Copy Agent";

  const invalidateProjectCaches = (target: string) => {
    queryClient.invalidateQueries({ queryKey: ["useGetFolders"] });
    queryClient.invalidateQueries({ queryKey: ["useGetFolder", target] });
    if (currentProjectId) {
      queryClient.invalidateQueries({
        queryKey: ["useGetFolder", currentProjectId],
      });
    }
    queryClient.invalidateQueries({
      queryKey: ["useGetRefreshAgentsQuery"],
    });
  };

  const handleSubmit = async () => {
    if (!agent?.data) {
      setErrorData({
        title: "Unable to transfer agent",
        list: ["Agent data is unavailable. Please refresh and try again."],
      });
      return;
    }

    if (creatingNewProject) {
      if (!newProjectName.trim()) {
        setErrorData({
          title: "Project name is required",
          list: ["Enter a name for the new project."],
        });
        return;
      }
    } else if (!targetProjectId) {
      setErrorData({
        title: "Select a target project",
        list: ["Choose a project before continuing."],
      });
      return;
    }

    setIsSubmitting(true);
    try {
      // Resolve target project id (create one first if requested)
      let resolvedTargetId = targetProjectId;
      if (creatingNewProject) {
        const created = (await postFolder({
          data: {
            name: newProjectName.trim(),
            description: "",
            parent_id: null,
          },
        })) as unknown as { id?: string } | undefined;

        if (!created?.id) {
          throw new Error("Project creation did not return an id");
        }
        resolvedTargetId = created.id;
      }

      if (mode === "move") {
        // Move = update project_id on the existing row. Preserves the agent
        // ID, name (no "(1)" suffix), deployments, runs, and references.
        await patchAgent({
          id: agent.id,
          project_id: resolvedTargetId,
        });

        // Reflect the move in the in-memory agents store so the source
        // project's card count drops immediately without waiting for refetch.
        const currentAgents = useAgentsManagerStore.getState().agents ?? [];
        setAgents(
          currentAgents.map((item) =>
            item.id === agent.id
              ? { ...item, project_id: resolvedTargetId }
              : item,
          ),
        );
      } else {
        // Copy = create a new agent in the target project.
        const newAgent = createNewAgent(agent.data, resolvedTargetId, agent);
        const createdAgent = await postAddAgent(newAgent);
        if (createdAgent?.id) {
          const currentAgents = useAgentsManagerStore.getState().agents ?? [];
          if (!currentAgents.some((item) => item.id === createdAgent.id)) {
            setAgents([...currentAgents, createdAgent]);
          }
        }
      }

      invalidateProjectCaches(resolvedTargetId);

      setSuccessData({
        title:
          mode === "move"
            ? creatingNewProject
              ? "Agent moved to the new project"
              : "Agent moved to the selected project"
            : creatingNewProject
              ? "Agent copied to the new project"
              : "Agent copied to the selected project",
      });
      setOpen(false);
    } catch (error) {
      console.error(error);
      setErrorData({
        title:
          mode === "move" ? "Failed to move agent" : "Failed to copy agent",
        list: ["Please try again."],
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <BaseModal open={open} setOpen={setOpen} size="small-query">
      <BaseModal.Header
        description={
          mode === "move"
            ? "Move this agent to a different project."
            : "Copy this agent into another project."
        }
      >
        {mode === "move" ? "Move Agent" : "Copy Agent"}
      </BaseModal.Header>
      <BaseModal.Content className="flex flex-col gap-4 p-4">
        <Alert className="border-yellow-200 bg-yellow-50 text-yellow-900">
          <AlertTitle>{warningTitle}</AlertTitle>
          <AlertDescription>
            <p>{warningDescription}</p>
            {deploymentDescription && (
              <p className="mt-2">{deploymentDescription}</p>
            )}
          </AlertDescription>
        </Alert>

        <div className="space-y-2">
          <Label htmlFor="transfer-project">Target project</Label>
          <Select
            value={creatingNewProject ? CREATE_NEW_VALUE : targetProjectId}
            onValueChange={(value) => {
              if (value === CREATE_NEW_VALUE) {
                setCreatingNewProject(true);
                setTargetProjectId("");
                return;
              }
              setCreatingNewProject(false);
              setTargetProjectId(value);
            }}
          >
            <SelectTrigger id="transfer-project">
              <SelectValue placeholder="Select a project" />
            </SelectTrigger>
            <SelectContent className="max-h-72 overflow-y-auto">
              <SelectItem value={CREATE_NEW_VALUE}>
                Create new project...
              </SelectItem>
              {availableProjects.length === 0 ? (
                <SelectItem value="__none__" disabled>
                  No other projects available
                </SelectItem>
              ) : (
                availableProjects.map((folder) => (
                  <SelectItem key={folder.id} value={folder.id}>
                    {folder.name}
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        </div>

        {creatingNewProject && (
          <div className="space-y-2">
            <Label htmlFor="new-project-name">New project name</Label>
            <Input
              id="new-project-name"
              value={newProjectName}
              onChange={(event) => setNewProjectName(event.target.value)}
              placeholder="e.g. Customer Support"
              autoFocus
              onKeyDown={(event) => {
                if (event.key === "Enter" && canSubmit) {
                  event.preventDefault();
                  void handleSubmit();
                }
              }}
            />
          </div>
        )}
      </BaseModal.Content>
      <BaseModal.Footer
        submit={{
          label: submitLabel,
          onClick: handleSubmit,
          loading: isSubmitting,
          disabled: !canSubmit,
          dataTestId: mode === "move" ? "btn-move-agent" : "btn-copy-agent",
        }}
      />
    </BaseModal>
  );
};

export default AgentTransferModal;
