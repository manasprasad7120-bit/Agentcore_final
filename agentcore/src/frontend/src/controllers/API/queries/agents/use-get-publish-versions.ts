import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IPublishVersionRecord {
  id: string;
  agent_id: string;
  version_number: string;
  agent_name: string;
  agent_description: string | null;
  publish_description: string | null;
  published_by: string;
  published_at: string;
  is_active: boolean;
  is_enabled: boolean;
  status: string;
  visibility: "PUBLIC" | "PRIVATE";
  error_message: string | null;
  environment: "uat" | "prod";
  promoted_from_uat_id: string | null;
}

export interface IGetPublishVersionsParams {
  agent_id: string;
  env: "uat" | "prod";
}

export const useGetPublishVersions: useQueryFunctionType<
  IGetPublishVersionsParams,
  IPublishVersionRecord[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const isValidUuid =
    !!params?.agent_id &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      params.agent_id,
    );

  const getPublishVersionsFn = async (): Promise<IPublishVersionRecord[]> => {
    if (!params?.agent_id) {
      return [];
    }

    const response = await api.get<IPublishVersionRecord[]>(
      `${getURL("PUBLISH")}/${params.agent_id}/versions/${params.env}`,
    );
    return response.data ?? [];
  };

  const queryResult: UseQueryResult<IPublishVersionRecord[]> = query(
    ["useGetPublishVersions", params?.agent_id, params?.env],
    getPublishVersionsFn,
    {
      enabled: isValidUuid,
      ...options,
    },
  );

  return queryResult;
};
