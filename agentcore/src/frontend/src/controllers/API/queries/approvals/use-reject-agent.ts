import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import { emitDashboardRefresh } from "@/utils/dashboardRefresh";

interface RejectAgentParams {
  agentId: string;
  comments: string;
  reason?: string;
  attachments?: File[];
}

/**
 * Hook to reject an agent
 * Sends rejection request with comments and optional reason to the backend
 */
export const useRejectAgent: useMutationFunctionType<
  undefined,
  RejectAgentParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const rejectAgentFn = async (
    params: RejectAgentParams,
  ): Promise<void> => {
    const formData = new FormData();
    formData.append("comments", params.comments ?? "");
    formData.append("reason", params.reason || "Not approved");
    for (const file of params.attachments ?? []) {
      formData.append("attachments", file);
    }

    await api.post(
      `${getURL("APPROVALS")}/${params.agentId}/reject`,
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
      },
    );
  };

  const mutation: UseMutationResult<
    void,
    any,
    RejectAgentParams
  > = mutate(["useRejectAgent"], rejectAgentFn, {
    ...options,
    onSuccess: (data, variables, context) => {
      emitDashboardRefresh();
      options?.onSuccess?.(data, variables, context);
    },
    onSettled: (data, error, variables, context) => {
      // Refetch approvals list after rejection
      queryClient.refetchQueries({ queryKey: ["useGetApprovals"] });
      options?.onSettled?.(data, error, variables, context);
    },
  });

  return mutation;
};
