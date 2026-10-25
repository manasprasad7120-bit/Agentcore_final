import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type TransitivePackage = {
  id: string;
  name: string;
  service_name: string;
  resolved_version: string;
  required_by: string[];
  required_by_details: { name: string; version: string }[];
  required_by_chain: string[];
  required_by_chain_details: { name: string; version: string }[];
  managed_roots: string[];
  managed_root_details: { name: string; version: string }[];
  dependency_paths: string[];
  start_date: string;
  end_date: string;
  is_current: boolean;
  scope: "managed_closure" | "full_graph";
  source: Record<string, unknown>;
};

export type GetTransitivePackagesParams = {
  include_history?: boolean;
  include_full_graph?: boolean;
  service?: string;
  regionCode?: string | null;
};

export const useGetTransitivePackages: useQueryFunctionType<
  GetTransitivePackagesParams,
  TransitivePackage[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const includeHistory = params?.include_history ?? false;
  const includeFullGraph = params?.include_full_graph ?? false;
  const service = params?.service ?? "all";
  const regionCode = params?.regionCode ?? null;

  const getTransitivePackagesFn = async (): Promise<TransitivePackage[]> => {
    if (!isAuthenticated) return [];
    const res = await api.get(`${getURL("PACKAGES")}/transitive`, {
      params: {
        include_history: includeHistory,
        include_full_graph: includeFullGraph,
        service,
      },
      headers: regionCode ? { "X-Region-Code": regionCode } : undefined,
    });
    return res.data;
  };

  const queryResult: UseQueryResult<TransitivePackage[], any> = query(
    ["useGetTransitivePackages", includeHistory, includeFullGraph, service, regionCode ?? "local"],
    getTransitivePackagesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
