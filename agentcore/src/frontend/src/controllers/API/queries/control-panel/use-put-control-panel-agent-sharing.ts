import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { ControlPanelSharingResponse } from "./use-get-control-panel-agent-sharing";

export interface UpdateControlPanelAgentSharingPayload {
  deploy_id: string;
  recipient_emails: string[];
}

export const usePutControlPanelAgentSharing: useMutationFunctionType<
  ControlPanelSharingResponse,
  UpdateControlPanelAgentSharingPayload
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const updateSharingFn = async (
    payload: UpdateControlPanelAgentSharingPayload,
  ): Promise<ControlPanelSharingResponse> => {
    const res = await api.put<ControlPanelSharingResponse>(
      `${getURL("CONTROL_PANEL")}/agents/${payload.deploy_id}/sharing`,
      {
        recipient_emails: payload.recipient_emails ?? [],
      },
    );
    return res.data;
  };

  return mutate(["usePutControlPanelAgentSharing"], updateSharingFn, {
    ...options,
    onSettled: (...args) => {
      queryClient.invalidateQueries({ queryKey: ["useGetControlPanelAgents"] });
      queryClient.invalidateQueries({ queryKey: ["useGetControlPanelAgentSharing"] });
      options?.onSettled?.(...args);
    },
  });
};
