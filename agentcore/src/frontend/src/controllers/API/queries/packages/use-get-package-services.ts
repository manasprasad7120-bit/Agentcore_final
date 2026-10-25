import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type GetPackageServicesParams = {
  include_history?: boolean;
  regionCode?: string | null;
};

export const useGetPackageServices: useQueryFunctionType<
  GetPackageServicesParams,
  string[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const includeHistory = params?.include_history ?? false;
  const regionCode = params?.regionCode ?? null;

  const getPackageServicesFn = async (): Promise<string[]> => {
    if (!isAuthenticated) return [];
    const res = await api.get(`${getURL("PACKAGES")}/services`, {
      params: {
        include_history: includeHistory,
      },
      headers: regionCode ? { "X-Region-Code": regionCode } : undefined,
    });
    return res.data;
  };

  const queryResult: UseQueryResult<string[], any> = query(
    ["useGetPackageServices", includeHistory, regionCode ?? "local"],
    getPackageServicesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
