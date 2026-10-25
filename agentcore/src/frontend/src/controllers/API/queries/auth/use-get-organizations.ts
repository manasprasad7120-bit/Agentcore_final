import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type OrganizationListItem = {
  id: string;
  name: string;
  status?: string | null;
};

export const useGetOrganizations: useMutationFunctionType<
  OrganizationListItem[],
  undefined
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function getOrganizations(): Promise<OrganizationListItem[]> {
    const res = await api.get(`${getURL("USERS")}/organizations`);
    if (res.status === 200) {
      return res.data ?? [];
    }
    return [];
  }

  const mutation: UseMutationResult<OrganizationListItem[], any, undefined> = mutate(
    ["useGetOrganizations"],
    getOrganizations,
    options,
  );

  return mutation;
};
