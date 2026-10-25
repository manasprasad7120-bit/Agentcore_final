import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ReleaseRecord = {
  id: string;
  version: string;
  major: number;
  minor: number;
  patch: number;
  release_notes: string;
  start_date: string;
  end_date: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  is_active: boolean;
  package_count?: number;
  has_document: boolean;
  document_file_name: string | null;
  document_content_type: string | null;
  document_size: number | null;
  document_uploaded_by: string | null;
  document_uploaded_at: string | null;
};

type ReleaseQueryParams = {
  regionCode?: string | null;
};

export const useGetReleases: useQueryFunctionType<ReleaseQueryParams | undefined, ReleaseRecord[]> = (
  params,
  options?: any,
) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getReleasesFn = async (): Promise<ReleaseRecord[]> => {
    if (!isAuthenticated) return [];
    const config = params?.regionCode ? { headers: { "X-Region-Code": params.regionCode } } : undefined;
    const res = await api.get(`${getURL("RELEASES")}`, config);
    return res.data;
  };

  const queryResult: UseQueryResult<ReleaseRecord[], any> = query(
    ["useGetReleases", params?.regionCode ?? "local"],
    getReleasesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
