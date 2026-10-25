import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ReleasePackageComparisonRecord = {
  release_id: string;
  service_name: string;
  package_type: "managed" | "transitive" | string;
  name: string;
  released_version: string | null;
  released_version_spec: string | null;
  current_version: string | null;
  current_version_spec: string | null;
  status: "unchanged" | "upgraded" | "downgraded" | "new" | "removed" | "changed";
};

export const useGetReleasePackageComparison: useQueryFunctionType<
  { releaseId: string; service?: string; regionCode?: string | null },
  ReleasePackageComparisonRecord[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getReleasePackageComparisonFn = async (): Promise<ReleasePackageComparisonRecord[]> => {
    if (!isAuthenticated || !params?.releaseId) return [];
    const res = await api.get(`${getURL("RELEASES")}/${params.releaseId}/package-comparison`, {
      params: {
        service: params?.service ?? "all",
      },
      ...(params?.regionCode ? { headers: { "X-Region-Code": params.regionCode } } : {}),
    });
    return res.data;
  };

  const queryResult: UseQueryResult<ReleasePackageComparisonRecord[], any> = query(
    [
      "useGetReleasePackageComparison",
      params?.releaseId,
      params?.service ?? "all",
      params?.regionCode ?? "local",
    ],
    getReleasePackageComparisonFn,
    {
      enabled: Boolean(params?.releaseId) && isAuthenticated,
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
