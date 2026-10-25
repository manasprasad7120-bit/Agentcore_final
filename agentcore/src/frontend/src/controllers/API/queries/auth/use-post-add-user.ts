import type { UseMutationResult } from "@tanstack/react-query";
import type { Users, useMutationFunctionType } from "@/types/api";
import type { UserInputType } from "@/types/components";
import useAlertStore from "@/stores/alertStore";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface UserMutationResult<T> {
  data: T;
  emailSent: boolean;
  warningMessage?: string;
}

export const useAddUser: useMutationFunctionType<undefined, UserInputType> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const addUserFunction = async (
    user: UserInputType,
  ): Promise<UserMutationResult<Array<Users>>> => {
    const res = await api.post(`${getURL("USERS")}/`, user);
    const warningMessage = res.headers["x-agentcore-warning"];
    const warningTitle = res.headers["x-agentcore-warning-title"];
    const emailStatus = res.headers["x-agentcore-notification-email-status"];

    if (warningMessage) {
      setErrorData({
        title:
          typeof warningTitle === "string" && warningTitle.trim().length > 0
            ? warningTitle
            : "Warning",
        list: [warningMessage],
      });
    }

    return {
      data: res.data,
      emailSent: emailStatus === "sent",
      warningMessage:
        typeof warningMessage === "string" ? warningMessage : undefined,
    };
  };

  const mutation: UseMutationResult<
    UserMutationResult<Array<Users>>,
    any,
    UserInputType
  > = mutate(
    ["useAddUser"],
    addUserFunction,
    options,
  );

  return mutation;
};
