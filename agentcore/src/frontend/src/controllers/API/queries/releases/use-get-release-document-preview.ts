import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ReleaseDocumentPreviewRecord = {
  html: string;
  file_name: string | null;
  document_uploaded_at: string | null;
  document_size: number | null;
  has_document: boolean;
  office_viewer_url?: string | null;
};

export const useGetReleaseDocumentPreview: useQueryFunctionType<
  { releaseId: string; regionCode?: string | null },
  ReleaseDocumentPreviewRecord | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getReleaseDocumentPreviewFn = async (): Promise<ReleaseDocumentPreviewRecord | null> => {
    if (!isAuthenticated || !params?.releaseId) return null;
    const config = params?.regionCode ? { headers: { "X-Region-Code": params.regionCode } } : undefined;
    const res = await api.get(`${getURL("RELEASES")}/${params.releaseId}/document/preview`, config);
    return res.data;
  };

  const queryResult: UseQueryResult<ReleaseDocumentPreviewRecord | null, any> = query(
    ["useGetReleaseDocumentPreview", params?.releaseId, params?.regionCode ?? "local"],
    getReleaseDocumentPreviewFn,
    {
      enabled: Boolean(params?.releaseId) && isAuthenticated,
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
