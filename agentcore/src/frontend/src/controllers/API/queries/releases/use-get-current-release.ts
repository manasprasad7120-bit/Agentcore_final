import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import { useDarkStore } from "@/stores/darkStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { ReleaseRecord } from "./use-get-releases";

export const useGetCurrentRelease: useQueryFunctionType<
  { regionCode?: string | null } | undefined,
  ReleaseRecord | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const permissions = useAuthStore((state) => state.permissions);
  const role = useAuthStore((state) => state.role);
  const canViewReleaseManagement =
    String(role ?? "").toLowerCase() === "root" ||
    permissions.includes("view_release_management_page");

  const getCurrentReleaseFn = async (): Promise<ReleaseRecord | null> => {
    if (!isAuthenticated || !canViewReleaseManagement) return null;
    const config = params?.regionCode ? { headers: { "X-Region-Code": params.regionCode } } : undefined;
    const res = await api.get(`${getURL("RELEASES")}/current`, config);
    return res.data;
  };

  const responseFn = async (): Promise<ReleaseRecord | null> => {
    const data = await getCurrentReleaseFn();
    // Always update the store when fetching the local/hub region (no cross-region header).
    // Root admins also have regionCode set, so the old `!regionCode` guard blocked them.
    const refreshCurrentReleaseVersion = useDarkStore.getState().refreshCurrentReleaseVersion;
    if (!params?.regionCode) {
      refreshCurrentReleaseVersion(data?.version ?? "");
    }
    return data;
  };

  const queryResult: UseQueryResult<ReleaseRecord | null, any> = query(
    ["useGetCurrentRelease", params?.regionCode ?? "local"],
    responseFn,
    {
      refetchOnWindowFocus: false,
      ...options,
      enabled:
        (options?.enabled ?? true) && isAuthenticated && canViewReleaseManagement,
    },
  );

  return queryResult;
};
