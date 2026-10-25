import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IPublishDepartmentOption {
  id: string;
  name: string;
  org_id: string;
}

export const useGetPublishDepartments: useQueryFunctionType<
  { agent_id: string },
  IPublishDepartmentOption[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const fn = async (): Promise<IPublishDepartmentOption[]> => {
    if (!params?.agent_id?.trim()) return [];
    const res = await api.get<IPublishDepartmentOption[]>(
      `${getURL("PUBLISH")}/${params.agent_id}/departments`,
    );
    return res.data ?? [];
  };

  const queryResult: UseQueryResult<IPublishDepartmentOption[]> = query(
    ["useGetPublishDepartments", params?.agent_id],
    fn,
    {
      enabled: Boolean(params?.agent_id?.trim()),
      ...options,
    },
  );

  return queryResult;
};
