import { useMutation } from "@tanstack/react-query";
import { api } from "../../api";
import type {
  McpRiskAnalysisResponse,
  McpRiskAnalyzeRequest,
} from "@/types/mcp";

export const useAnalyzeMCPRisk = () => {
  return useMutation<McpRiskAnalysisResponse, Error, McpRiskAnalyzeRequest>({
    mutationFn: async (body) => {
      const response = await api.post(
        "api/mcp/registry/analyze-risk",
        body,
      );
      return response.data;
    },
  });
};
