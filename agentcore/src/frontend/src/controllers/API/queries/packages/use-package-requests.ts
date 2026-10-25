import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType, useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type PackageRequestStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "deployed"
  | "cancelled";

export interface PackageRequestItem {
  id: string;
  service_name: string;
  package_name: string;
  requested_version: string;
  justification: string;
  status: PackageRequestStatus;
  requested_by: string;
  requested_by_name?: string | null;
  requested_by_email?: string | null;
  reviewed_by?: string | null;
  deployed_by?: string | null;
  review_comments?: string | null;
  deployment_notes?: string | null;
  requested_at: string;
  reviewed_at?: string | null;
  deployed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreatePackageRequestPayload {
  service_name: string;
  package_name: string;
  requested_version: string;
  justification: string;
  regionCode?: string | null;
}

export const useGetMyPackageRequests: useQueryFunctionType<
  { regionCode?: string | null } | undefined,
  PackageRequestItem[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const regionCode = params?.regionCode ?? null;

  const fn = async (): Promise<PackageRequestItem[]> => {
    const res = await api.get(`${getURL("PACKAGES")}/requests/mine`, {
      headers: regionCode ? { "X-Region-Code": regionCode } : undefined,
    });
    return res.data;
  };

  return query(["useGetMyPackageRequests", regionCode ?? "local"], fn, options);
};

export const useGetPackageRequestsForApproval: useQueryFunctionType<
  { status?: string; regionCode?: string | null },
  PackageRequestItem[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();
  const regionCode = params?.regionCode ?? null;

  const fn = async (): Promise<PackageRequestItem[]> => {
    const res = await api.get(`${getURL("PACKAGES")}/requests`, {
      params: params?.status ? { status: params.status } : undefined,
      headers: regionCode ? { "X-Region-Code": regionCode } : undefined,
    });
    return res.data;
  };

  return query(
    ["useGetPackageRequestsForApproval", params?.status ?? "all", regionCode ?? "local"],
    fn,
    options,
  );
};

export const useCreatePackageRequest: useMutationFunctionType<
  undefined,
  CreatePackageRequestPayload,
  PackageRequestItem
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const fn = async (payload: CreatePackageRequestPayload): Promise<PackageRequestItem> => {
    const { regionCode, ...body } = payload;
    const res = await api.post(`${getURL("PACKAGES")}/requests`, body, {
      headers: regionCode ? { "X-Region-Code": regionCode } : undefined,
    });
    return res.data;
  };

  return mutate(["useCreatePackageRequest"], fn, {
    ...options,
    onSettled: () => {
      queryClient.refetchQueries({ queryKey: ["useGetMyPackageRequests"] });
      queryClient.refetchQueries({ queryKey: ["useGetPackageRequestsForApproval"] });
    },
  });
};

interface RequestActionPayload {
  requestId: string;
  comments?: string;
  regionCode?: string | null;
}

interface DeployActionPayload {
  requestId: string;
  deployment_notes?: string;
  regionCode?: string | null;
}

export const useApprovePackageRequest: useMutationFunctionType<
  undefined,
  RequestActionPayload,
  PackageRequestItem
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const fn = async (payload: RequestActionPayload): Promise<PackageRequestItem> => {
    const res = await api.post(
      `${getURL("PACKAGES")}/requests/${payload.requestId}/approve`,
      { comments: payload.comments ?? "" },
      {
        headers: payload.regionCode ? { "X-Region-Code": payload.regionCode } : undefined,
      },
    );
    return res.data;
  };

  return mutate(["useApprovePackageRequest"], fn, {
    ...options,
    onSettled: () => {
      queryClient.refetchQueries({ queryKey: ["useGetMyPackageRequests"] });
      queryClient.refetchQueries({ queryKey: ["useGetPackageRequestsForApproval"] });
      queryClient.refetchQueries({ queryKey: ["useGetApprovals"] });
    },
  });
};

export const useRejectPackageRequest: useMutationFunctionType<
  undefined,
  RequestActionPayload,
  PackageRequestItem
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const fn = async (payload: RequestActionPayload): Promise<PackageRequestItem> => {
    const res = await api.post(
      `${getURL("PACKAGES")}/requests/${payload.requestId}/reject`,
      { comments: payload.comments ?? "" },
      {
        headers: payload.regionCode ? { "X-Region-Code": payload.regionCode } : undefined,
      },
    );
    return res.data;
  };

  return mutate(["useRejectPackageRequest"], fn, {
    ...options,
    onSettled: () => {
      queryClient.refetchQueries({ queryKey: ["useGetMyPackageRequests"] });
      queryClient.refetchQueries({ queryKey: ["useGetPackageRequestsForApproval"] });
      queryClient.refetchQueries({ queryKey: ["useGetApprovals"] });
    },
  });
};

export const useDeployPackageRequest: useMutationFunctionType<
  undefined,
  DeployActionPayload,
  PackageRequestItem
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const fn = async (payload: DeployActionPayload): Promise<PackageRequestItem> => {
    const res = await api.post(
      `${getURL("PACKAGES")}/requests/${payload.requestId}/deploy`,
      { deployment_notes: payload.deployment_notes ?? "" },
      {
        headers: payload.regionCode ? { "X-Region-Code": payload.regionCode } : undefined,
      },
    );
    return res.data;
  };

  return mutate(["useDeployPackageRequest"], fn, {
    ...options,
    onSettled: () => {
      queryClient.refetchQueries({ queryKey: ["useGetMyPackageRequests"] });
      queryClient.refetchQueries({ queryKey: ["useGetPackageRequestsForApproval"] });
      queryClient.refetchQueries({ queryKey: ["useGetApprovals"] });
    },
  });
};
