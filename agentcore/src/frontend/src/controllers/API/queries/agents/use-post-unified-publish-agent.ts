import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import { emitDashboardRefresh } from "@/utils/dashboardRefresh";

export interface IUnifiedPublishAgentRequest {
  agent_id: string;
  department_id?: string;
  department_admin_id?: string;
  visibility: "PUBLIC" | "PRIVATE";
  environment: "uat" | "prod";
  published_agent_name?: string;
  publish_description?: string;
  recipient_emails?: string[];
}

export interface IUnifiedPublishAgentResponse {
  success: boolean;
  message: string;
  publish_id: string;
  environment: "uat" | "prod";
  status: string;
  is_active: boolean;
  version_number: string;
}

export const usePostUnifiedPublishAgent: useMutationFunctionType<
  undefined,
  IUnifiedPublishAgentRequest,
  IUnifiedPublishAgentResponse
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const publishAgentFn = async (
    payload: IUnifiedPublishAgentRequest,
  ): Promise<IUnifiedPublishAgentResponse> => {
    const response = await api.post<IUnifiedPublishAgentResponse>(
      `${getURL("PUBLISH")}/${payload.agent_id}`,
      {
        ...(payload.department_id ? { department_id: payload.department_id } : {}),
        ...(payload.department_admin_id
          ? { department_admin_id: payload.department_admin_id }
          : {}),
        visibility: payload.visibility,
        environment: payload.environment,
        published_agent_name: payload.published_agent_name ?? null,
        publish_description: payload.publish_description ?? null,
        recipient_emails: payload.recipient_emails ?? [],
      },
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    IUnifiedPublishAgentResponse,
    any,
    IUnifiedPublishAgentRequest
  > = mutate(["usePostUnifiedPublishAgent"], publishAgentFn, {
    ...options,
    onSuccess: (data, variables, context) => {
      emitDashboardRefresh();
      options?.onSuccess?.(data, variables, context);
    },
    onSettled: (data, error, variables, context) => {
      queryClient.invalidateQueries({
        queryKey: ["useGetPublishStatus"],
      });
      options?.onSettled?.(data, error, variables, context);
    },
  });

  return mutation;
};
