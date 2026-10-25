import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import cloneDeep from "lodash/cloneDeep";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useGetFoldersQuery } from "@/controllers/API/queries/folders/use-get-folders";
import { usePostRegistryClone } from "@/controllers/API/queries/registry";
import { usePostAddAgent } from "@/controllers/API/queries/agents/use-post-add-agent";
import useAlertStore from "@/stores/alertStore";
import type { AgentType } from "@/types/agent";

type RegistrySource = {
  type: "registry";
  registryId: string;
  title: string;
};

type AgentSource = {
  type: "agent";
  agent: AgentType;
};

export type CopyAgentDialogSource = RegistrySource | AgentSource;

interface CopyAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  source: CopyAgentDialogSource | null;
  onSuccess?: (agentId: string, projectId: string) => void;
}

const DEFAULT_VIEWPORT = { zoom: 1, x: 0, y: 0 };

export default function CopyAgentDialog({
  open,
  onOpenChange,
  source,
  onSuccess,
}: CopyAgentDialogProps): JSX.Element | null {
  const { t } = useTranslation();
  const { permissions, role, userData } = useContext(AuthContext);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [cloneName, setCloneName] = useState("");
  const [createProject, setCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDescription, setNewProjectDescription] = useState("");
  const previousOpenRef = useRef(false);

  const canCopy = permissions?.includes("copy_agents");
  const { data: folders = [], refetch: refetchFolders } = useGetFoldersQuery({
    staleTime: 0,
  });
  const cloneRegistryMutation = usePostRegistryClone();
  const createAgentMutation = usePostAddAgent();

  const normalizedRole = String(role ?? "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const isAdminRole = [
    "root",
    "super_admin",
    "department_admin",
  ].includes(normalizedRole);
  const currentUserEmail = String(userData?.email ?? "").toLowerCase();

  const foldersForClone = useMemo(() => {
    if (!isAdminRole) return folders;
    return folders.filter((folder) => {
      if (folder.is_own_project) return true;
      if (folder.created_by_email) {
        return folder.created_by_email.toLowerCase() === currentUserEmail;
      }
      return false;
    });
  }, [folders, isAdminRole, currentUserEmail]);

  const sourceKey = useMemo(() => {
    if (!source) return "";
    return source.type === "registry"
      ? `registry:${source.registryId}`
      : `agent:${source.agent.id}`;
  }, [source]);

  useEffect(() => {
    if (!selectedProjectId && foldersForClone.length > 0) {
      setSelectedProjectId(String(foldersForClone[0].id || ""));
    }
  }, [foldersForClone, selectedProjectId]);

  useEffect(() => {
    const isOpening = open && !previousOpenRef.current;
    previousOpenRef.current = open;

    if (!open || !source || !isOpening) return;
    const defaultName =
      source.type === "registry"
        ? `${source.title} (Copy)`
        : `${source.agent.name} (Copy)`;
    setCloneName(defaultName);
    setCreateProject(false);
    setNewProjectName("");
    setNewProjectDescription("");
  }, [open, sourceKey, source]);

  const handleClone = async () => {
    try {
      if (!source) return;
      if (!canCopy) {
        setErrorData({ title: t("You don't have permission to copy") });
        return;
      }

      let projectId = selectedProjectId;
      if (createProject) {
        if (!newProjectName.trim()) {
          setErrorData({ title: t("Project name is required") });
          return;
        }
        const created = await api.post(`${getURL("PROJECTS")}/`, {
          name: newProjectName.trim(),
          description: newProjectDescription.trim(),
          agents_list: [],
          components_list: [],
        });
        projectId = String(created?.data?.id || "");
        const refreshed = await refetchFolders();
        if (!projectId) {
          const updatedFolders = refreshed?.data || folders;
          const fallback = updatedFolders.find(
            (f) => f.name === newProjectName.trim(),
          );
          projectId = String(fallback?.id || "");
        }
      }

      if (!projectId) {
        setErrorData({ title: t("Please select a project first") });
        return;
      }

      if (source.type === "registry") {
        const response = await cloneRegistryMutation.mutateAsync({
          registry_id: source.registryId,
          project_id: projectId,
          new_name: cloneName.trim() || undefined,
        });
        setSuccessData({
          title: t("Agent '{{name}}' copied successfully", {
            name: response.agent_name,
          }),
        });
        onOpenChange(false);
        onSuccess?.(response.agent_id, projectId);
        return;
      }

      const agentData =
        source.agent.data ??
        ({
          nodes: [],
          edges: [],
          viewport: DEFAULT_VIEWPORT,
        } as AgentType["data"]);

      const created = await createAgentMutation.mutateAsync({
        name: cloneName.trim() || `${source.agent.name} (Copy)`,
        data: cloneDeep(agentData!),
        description: source.agent.description ?? "",
        is_component: Boolean(source.agent.is_component),
        project_id: projectId,
        endpoint_name: source.agent.endpoint_name ?? undefined,
        icon: source.agent.icon ?? undefined,
        gradient: source.agent.gradient ?? undefined,
        tags: source.agent.tags ?? undefined,
      });

      setSuccessData({
        title: t("Agent '{{name}}' copied successfully", {
          name: created?.name || cloneName.trim() || source.agent.name,
        }),
      });
      onOpenChange(false);
      onSuccess?.(created?.id, projectId);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to copy agent"),
        list: [error?.response?.data?.detail || t("Please try again")],
      });
    }
  };

  if (!source) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("Copy Agent")}</DialogTitle>
          <DialogDescription>
            {source.type === "registry"
              ? t(
                  "Choose existing project or create a new project, then copy this registry agent.",
                )
              : t(
                  "Choose existing project or create a new project, then copy this agent.",
                )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 text-sm">
          <label className="block">
            <span className="mb-1 block text-xs text-muted-foreground">
              {t("Agent Name")}
            </span>
            <input
              value={cloneName}
              onChange={(e) => setCloneName(e.target.value)}
              className="w-full rounded-md border bg-card px-3 py-2"
              placeholder={t("Copied agent name")}
            />
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={createProject}
              onChange={(e) => setCreateProject(e.target.checked)}
            />
            <span>{t("Create new project and copy there")}</span>
          </label>

          {createProject ? (
            <div className="space-y-2">
              <input
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                className="w-full rounded-md border bg-card px-3 py-2"
                placeholder={t("New project name")}
              />
              <textarea
                value={newProjectDescription}
                onChange={(e) => setNewProjectDescription(e.target.value)}
                className="w-full rounded-md border bg-card px-3 py-2"
                placeholder={t("New project description (optional)")}
              />
            </div>
          ) : (
            <select
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              className="w-full rounded-md border bg-card px-3 py-2"
            >
              <option value="">{t("Select project")}</option>
              {foldersForClone.map((folder) => (
                <option
                  key={folder.id || folder.name}
                  value={String(folder.id || "")}
                >
                  {folder.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("Cancel")}
          </Button>
          <Button
            onClick={handleClone}
            disabled={
              cloneRegistryMutation.isLoading || createAgentMutation.isLoading
            }
          >
            {cloneRegistryMutation.isLoading || createAgentMutation.isLoading
              ? t("Copying...")
              : t("Copy Agent")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
