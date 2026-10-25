import { useCallback } from "react";
import {
  useApproveAgent,
  useRejectAgent,
} from "@/controllers/API/queries/approvals";
import {
  useApprovePackageRequest,
  useRejectPackageRequest,
} from "@/controllers/API/queries/packages";
import useAlertStore from "@/stores/alertStore";
import type { ApprovalAgent } from "@/controllers/API/queries/approvals";

const entityLabel = (entityType?: string) =>
  entityType === "model" ? "Model" : entityType === "mcp" ? "MCP request" : entityType === "package" ? "Package request" : "Agent";

/**
 * Custom hook to handle approval and rejection actions
 * Combines API mutations and user feedback notifications
 */
export const useApprovalActions = (regionCode?: string | null) => {
  const setSuccessData = useAlertStore((s) => s.setSuccessData);
  const setErrorData = useAlertStore((s) => s.setErrorData);

  // API mutation hooks
  const approveAgentMutation = useApproveAgent();
  const rejectAgentMutation = useRejectAgent();
  const approvePackageMutation = useApprovePackageRequest();
  const rejectPackageMutation = useRejectPackageRequest();

  /**
   * Handle agent approval
   * Sends comments + attachments in one approve request
   */
  const handleApprove = useCallback(
    async (
      agent: ApprovalAgent,
      comments: string,
      attachments: File[],
    ) => {
      try {
        await new Promise((resolve, reject) => {
          if (agent.entityType === "package") {
            approvePackageMutation.mutate(
              {
                requestId: agent.id,
                comments,
                regionCode,
              },
              {
                onSuccess: () => {
                  setSuccessData({
                    title: `${entityLabel(agent.entityType)} "${agent.title}" approved successfully.`,
                    link: "/approval",
                  });
                  resolve(null);
                },
                onError: () => {
                  setErrorData({
                    title: `Failed to approve ${entityLabel(agent.entityType).toLowerCase()} "${agent.title}".`,
                    link: "/approval",
                  });
                  reject(new Error("Approval failed"));
                },
              },
            );
            return;
          }
          approveAgentMutation.mutate(
            {
              agentId: agent.id,
              comments,
              attachments,
            },
            {
              onSuccess: () => {
                setSuccessData({
                  title: `${entityLabel(agent.entityType)} "${agent.title}" approved successfully.`,
                  link: "/approval",
                });
                resolve(null);
              },
              onError: () => {
                setErrorData({
                  title: `Failed to approve ${entityLabel(agent.entityType).toLowerCase()} "${agent.title}".`,
                  link: "/approval",
                });
                reject(new Error("Approval failed"));
              },
            },
          );
        });
      } catch (error) {
        console.error("Approval error:", error);
      }
    },
    [approveAgentMutation, approvePackageMutation, regionCode, setSuccessData, setErrorData],
  );

  /**
   * Handle agent rejection
   * Sends comments + attachments in one reject request
   */
  const handleReject = useCallback(
    async (
      agent: ApprovalAgent,
      comments: string,
      attachments: File[],
    ) => {
      try {
        await new Promise((resolve, reject) => {
          if (agent.entityType === "package") {
            rejectPackageMutation.mutate(
              {
                requestId: agent.id,
                comments,
                regionCode,
              },
              {
                onSuccess: () => {
                  setSuccessData({
                    title: `${entityLabel(agent.entityType)} "${agent.title}" rejected.`,
                    link: "/approval",
                  });
                  resolve(null);
                },
                onError: () => {
                  setErrorData({
                    title: `Failed to reject ${entityLabel(agent.entityType).toLowerCase()} "${agent.title}".`,
                    link: "/approval",
                  });
                  reject(new Error("Rejection failed"));
                },
              },
            );
            return;
          }
          rejectAgentMutation.mutate(
            {
              agentId: agent.id,
              comments,
              attachments,
            },
            {
              onSuccess: () => {
                setSuccessData({
                  title: `${entityLabel(agent.entityType)} "${agent.title}" rejected.`,
                  link: "/approval",
                });
                resolve(null);
              },
              onError: () => {
                setErrorData({
                  title: `Failed to reject ${entityLabel(agent.entityType).toLowerCase()} "${agent.title}".`,
                  link: "/approval",
                });
                reject(new Error("Rejection failed"));
              },
            },
          );
        });
      } catch (error) {
        console.error("Rejection error:", error);
      }
    },
    [rejectAgentMutation, rejectPackageMutation, regionCode, setSuccessData, setErrorData],
  );

  return {
    handleApprove,
    handleReject,
    isLoading:
      approveAgentMutation.isPending ||
      rejectAgentMutation.isPending ||
      approvePackageMutation.isPending ||
      rejectPackageMutation.isPending,
  };
};
