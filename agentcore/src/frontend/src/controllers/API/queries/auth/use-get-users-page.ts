import type { UseMutationResult } from "@tanstack/react-query";
import type { Users, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface getUsersQueryParams {
  skip: number;
  limit: number;
  role?: string;
  q?: string;
  organization_id?: string;
  department_id?: string;
  sort_by?: string;
  sort_order?: string;
}

export const useGetUsers: useMutationFunctionType<any, getUsersQueryParams> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function getUsers({
    skip,
    limit,
    role,
    q,
    organization_id,
    department_id,
    sort_by,
    sort_order,
  }: getUsersQueryParams): Promise<Array<Users>> {
    const roleParam = role ? `&role=${encodeURIComponent(role)}` : "";
    const qParam = q ? `&q=${encodeURIComponent(q)}` : "";
    const orgParam = organization_id
      ? `&organization_id=${encodeURIComponent(organization_id)}`
      : "";
    const deptParam = department_id
      ? `&department_id=${encodeURIComponent(department_id)}`
      : "";
    const sortByParam = sort_by ? `&sort_by=${encodeURIComponent(sort_by)}` : "";
    const sortOrderParam = sort_order
      ? `&sort_order=${encodeURIComponent(sort_order)}`
      : "";
    const res = await api.get(
      `${getURL("USERS")}/?skip=${skip}&limit=${limit}${roleParam}${qParam}${orgParam}${deptParam}${sortByParam}${sortOrderParam}`,
    );
    if (res.status === 200) {
      return res.data;
    }
    return [];
  }

  const mutation: UseMutationResult<
    getUsersQueryParams,
    any,
    getUsersQueryParams
  > = mutate(["useGetUsers"], getUsers, options);

  return mutation;
};
