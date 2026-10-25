import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface OrchAgentSummary {
  deploy_id: string;
  agent_id: string;
  agent_name: string;
  agent_description: string | null;
  version_number: number;
  version_label: string;
  environment: "uat" | "prod" | string;
  promoted_from_uat_id?: string | null;
  source_uat_version_number?: number | null;
}

export const useGetOrchAgents: useQueryFunctionType<
  undefined,
  OrchAgentSummary[]
> = (options?) => {
  const { query } = UseRequestProcessor();

  const getOrchAgentsFn = async (): Promise<OrchAgentSummary[]> => {
    const res = await api.get<OrchAgentSummary[]>(
      `${getURL("ORCHESTRATOR")}/agents`,
    );
    return res.data;
  };

  return query(["useGetOrchAgents"], getOrchAgentsFn, options);
};
