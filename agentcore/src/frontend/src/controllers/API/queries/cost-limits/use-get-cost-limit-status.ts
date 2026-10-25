import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import type { CostLimitStatus } from "./types";

export function useGetCostLimitStatus(
  enabled: boolean = true,
): UseQueryResult<CostLimitStatus[]> {
  return useQuery<CostLimitStatus[]>({
    queryKey: ["costLimitStatus"],
    queryFn: async () => {
      const res = await api.get(`${getURL("COST_LIMITS")}/status`);
      if (res.status === 200) {
        return res.data ?? [];
      }
      return [];
    },
    enabled,
    refetchInterval: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: true,
    retry: 1,
    staleTime: 60 * 1000, // 1 minute
  });
}
