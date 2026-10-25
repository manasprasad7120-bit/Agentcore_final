import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface DeleteParams {
  limit_id: string;
}

export const useDeleteCostLimit: useMutationFunctionType<
  undefined,
  DeleteParams
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function deleteCostLimit({ limit_id }: DeleteParams): Promise<any> {
    const res = await api.delete(`${getURL("COST_LIMITS")}/${limit_id}`);
    return res.data;
  }

  const mutation: UseMutationResult<any, any, DeleteParams> = mutate(
    ["useDeleteCostLimit"],
    deleteCostLimit,
    options,
  );

  return mutation;
};
