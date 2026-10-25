import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { CostLimitResponse } from "./types";

export const useGetCostLimits: useMutationFunctionType<
  CostLimitResponse[],
  undefined
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function getCostLimits(): Promise<CostLimitResponse[]> {
    const res = await api.get(`${getURL("COST_LIMITS")}`);
    if (res.status === 200) {
      return res.data ?? [];
    }
    return [];
  }

  const mutation: UseMutationResult<CostLimitResponse[], any, undefined> =
    mutate(["useGetCostLimits"], getCostLimits, options);

  return mutation;
};
