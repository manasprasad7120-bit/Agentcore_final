/**
 * Approvals API Query Hooks
 * 
 * This module exports all approval-related API hooks for fetching and managing agent approvals.
 * These hooks use React Query (tanstack/react-query) for caching and state management.
 */

export { useGetApprovals } from "./use-get-approvals";
export type { ApprovalAgent } from "./use-get-approvals";
export { useGetApprovalDetails } from "./use-get-approval-details";
export type { ApprovalDetails } from "./use-get-approval-details";
export { useGetApprovalPreview } from "./use-get-approval-preview";
export type { ApprovalPreviewResponse } from "./use-get-approval-preview";

export { useApproveAgent } from "./use-approve-agent";

export { useRejectAgent } from "./use-reject-agent";

export { useGetMcpApprovalConfig } from "./use-get-mcp-approval-config";
export { useProbeMcpApproval } from "./use-probe-mcp-approval";
export {
  useGetApprovalNotifications,
  useMarkApprovalNotificationRead,
  useMarkAllApprovalNotificationsRead,
  useDeleteAllApprovalNotifications,
} from "./use-approval-notifications";
export type { ApprovalNotification } from "./use-approval-notifications";
