import type { AgentType } from "@/types/agent";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IPostAddUploadAgentToFolder {
  agents: FormData;
  folderId: string;
}

export const usePostUploadAgentToFolder: useMutationFunctionType<
  undefined,
  IPostAddUploadAgentToFolder,
  AgentType[]
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const uploadAgentToFolderFn = async (
    payload: IPostAddUploadAgentToFolder,
  ): Promise<AgentType[]> => {
    const res = await api.post(
      `${getURL("AGENTS")}/upload/?project_id=${encodeURIComponent(payload.folderId)}`,
      payload.agents,
    );
    return res.data;
  };

  const mutation = mutate(
    ["usePostUploadAgentToFolder"],
    uploadAgentToFolderFn,
    {
      ...options,
      onSettled: () => {
        queryClient.refetchQueries({
          queryKey: ["useGetFolders"],
        });
        queryClient.refetchQueries({
          queryKey: ["useGetFolder"],
        });
      },
    },
  );

  return mutation;
};
