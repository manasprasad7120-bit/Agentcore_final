import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { useQueryFunctionType } from "@/types/api";
import type { AgentType } from "@/types/agent";
import { PREBUILT_TEMPLATES } from "@/data/prebuilt-templates";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetBasicExamplesQuery: useQueryFunctionType<
  undefined,
  AgentType[]
> = (options) => {
  const { query } = UseRequestProcessor();
  const setExamples = useAgentsManagerStore((state) => state.setExamples);

  const getBasicExamplesFn = async () => {
    return await api.get<AgentType[]>(`${getURL("AGENTS")}/basic_examples/`);
  };

  const responseFn = async () => {
    const { data } = await getBasicExamplesFn();
    const examples = data?.length ? data : PREBUILT_TEMPLATES;
    setExamples(examples);
    return examples;
  };

  const queryResult = query(["useGetBasicExamplesQuery"], responseFn, {
    ...options,
    retry: 3,
  });

  return queryResult;
};
