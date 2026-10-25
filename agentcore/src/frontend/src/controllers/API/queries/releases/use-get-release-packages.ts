import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ReleasePackageRecord = {
  id: string;
  release_id: string;
  service_name: string;
  name: string;
  version: string;
  version_spec: string | null;
  package_type: "managed" | "transitive" | string;
  required_by: string[];
  managed_roots: string[];
  managed_root_details: { name: string; version: string }[];
  dependency_paths: string[];
  source: Record<string, unknown>;
  captured_at: string;
};

export const useGetReleasePackages: useQueryFunctionType<
  { releaseId: string; service?: string; regionCode?: string | null },
  ReleasePackageRecord[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getReleasePackagesFn = async (): Promise<ReleasePackageRecord[]> => {
    if (!isAuthenticated || !params?.releaseId) return [];
    const res = await api.get(`${getURL("RELEASES")}/${params.releaseId}/packages`, {
      params: {
        service: params?.service ?? "all",
      },
      ...(params?.regionCode ? { headers: { "X-Region-Code": params.regionCode } } : {}),
    });
    return res.data;
  };

  const queryResult: UseQueryResult<ReleasePackageRecord[], any> = query(
    ["useGetReleasePackages", params?.releaseId, params?.service ?? "all", params?.regionCode ?? "local"],
    getReleasePackagesFn,
    {
      enabled: Boolean(params?.releaseId) && isAuthenticated,
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
