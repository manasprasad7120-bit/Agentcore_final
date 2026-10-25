import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { CostLimitCreatePayload, CostLimitResponse } from "./types";

export const useCreateCostLimit: useMutationFunctionType<
  undefined,
  CostLimitCreatePayload
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function createCostLimit(
    payload: CostLimitCreatePayload,
  ): Promise<CostLimitResponse> {
    const res = await api.post(`${getURL("COST_LIMITS")}`, payload);
    return res.data;
  }

  const mutation: UseMutationResult<
    CostLimitResponse,
    any,
    CostLimitCreatePayload
  > = mutate(["useCreateCostLimit"], createCostLimit, options);

  return mutation;
};
