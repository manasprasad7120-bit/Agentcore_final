import type { UseMutationResult } from "@tanstack/react-query";
import type { changeUser, useMutationFunctionType } from "@/types/api";
import useAlertStore from "@/stores/alertStore";
import type { UserMutationResult } from "./use-post-add-user";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface UpdateUserParams {
  user_id: string;
  user: changeUser;
}

export const useUpdateUser: useMutationFunctionType<
  undefined,
  UpdateUserParams
> = (options?) => {
  const { mutate } = UseRequestProcessor();
  const setErrorData = useAlertStore((state) => state.setErrorData);

  async function updateUser({
    user_id,
    user,
  }: UpdateUserParams): Promise<UserMutationResult<any>> {
    const res = await api.patch(`${getURL("USERS")}/${user_id}`, user);
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
  }

  const mutation: UseMutationResult<
    UserMutationResult<any>,
    any,
    UpdateUserParams
  > = mutate(["useUpdateUser"], updateUser, options);

  return mutation;
};
