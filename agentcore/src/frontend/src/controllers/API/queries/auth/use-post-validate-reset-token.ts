import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useValidateResetToken = (options?: any) => {
  const { mutate } = UseRequestProcessor();

  const mutationFn = async ({
    token,
  }: {
    token: string;
  }): Promise<{ valid: boolean }> => {
    const res = await api.post(`${getURL("VALIDATE_RESET_TOKEN")}`, { token });
    return res.data;
  };

  return mutate(["useValidateResetToken"], mutationFn, options);
};
