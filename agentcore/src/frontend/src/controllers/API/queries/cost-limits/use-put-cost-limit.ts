import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { CostLimitResponse, CostLimitUpdatePayload } from "./types";

interface UpdateParams {
  limit_id: string;
  payload: CostLimitUpdatePayload;
}

export const useUpdateCostLimit: useMutationFunctionType<
  undefined,
  UpdateParams
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function updateCostLimit({
    limit_id,
    payload,
  }: UpdateParams): Promise<CostLimitResponse> {
    const res = await api.put(
      `${getURL("COST_LIMITS")}/${limit_id}`,
      payload,
    );
    return res.data;
  }

  const mutation: UseMutationResult<CostLimitResponse, any, UpdateParams> =
    mutate(["useUpdateCostLimit"], updateCostLimit, options);

  return mutation;
};
