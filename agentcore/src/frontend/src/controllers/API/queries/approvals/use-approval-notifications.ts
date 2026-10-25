import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType, useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ApprovalNotification {
  id: string;
  title: string;
  link?: string | null;
  created_at: string;
  is_read: boolean;
}

export const useGetApprovalNotifications: useQueryFunctionType<
  undefined,
  ApprovalNotification[]
> = (options?) => {
  const { query } = UseRequestProcessor();

  const getNotificationsFn = async (): Promise<ApprovalNotification[]> => {
    const res = await api.get(`${getURL("APPROVALS")}/notifications`);
    return res.data;
  };

  return query(["useGetApprovalNotifications"], getNotificationsFn, options);
};

export const useMarkApprovalNotificationRead: useMutationFunctionType<
  undefined,
  { notificationId: string }
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const markReadFn = async ({ notificationId }: { notificationId: string }): Promise<void> => {
    await api.post(`${getURL("APPROVALS")}/notifications/${notificationId}/read`);
  };

  const mutation: UseMutationResult<void, any, { notificationId: string }> = mutate(
    ["useMarkApprovalNotificationRead"],
    markReadFn,
    {
      ...options,
      onSettled: (data, error, variables, context) => {
        queryClient.refetchQueries({ queryKey: ["useGetApprovalNotifications"] });
        options?.onSettled?.(data, error, variables, context);
      },
    },
  );

  return mutation;
};

export const useMarkAllApprovalNotificationsRead: useMutationFunctionType<
  undefined,
  undefined
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const markAllReadFn = async (): Promise<void> => {
    await api.post(`${getURL("APPROVALS")}/notifications/read-all`);
  };

  const mutation: UseMutationResult<void, any, void> = mutate(
    ["useMarkAllApprovalNotificationsRead"],
    markAllReadFn,
    {
      ...options,
      onSettled: (data, error, variables, context) => {
        queryClient.refetchQueries({ queryKey: ["useGetApprovalNotifications"] });
        options?.onSettled?.(data, error, variables, context);
      },
    },
  );

  return mutation;
};

export const useDeleteAllApprovalNotifications: useMutationFunctionType<
  undefined,
  undefined
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const deleteAllFn = async (): Promise<void> => {
    await api.delete(`${getURL("APPROVALS")}/notifications`);
  };

  const mutation: UseMutationResult<void, any, void> = mutate(
    ["useDeleteAllApprovalNotifications"],
    deleteAllFn,
    {
      ...options,
      onSettled: (data, error, variables, context) => {
        queryClient.refetchQueries({ queryKey: ["useGetApprovalNotifications"] });
        options?.onSettled?.(data, error, variables, context);
      },
    },
  );

  return mutation;
};
