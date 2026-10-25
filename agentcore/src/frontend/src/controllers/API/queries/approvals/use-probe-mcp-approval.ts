import { useMutation } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import type { McpProbeResponse } from "@/types/mcp";

export const useProbeMcpApproval = () => {
  return useMutation<McpProbeResponse, Error, { approval_id: string }>({
    mutationFn: async ({ approval_id }) => {
      const response = await api.post<McpProbeResponse>(
        `${getURL("APPROVALS")}/${approval_id}/mcp-probe`,
      );
      return response.data;
    },
  });
};
