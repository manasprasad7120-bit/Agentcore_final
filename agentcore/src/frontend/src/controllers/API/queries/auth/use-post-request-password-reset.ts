import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useRequestPasswordReset = (options?: any) => {
  const { mutate } = UseRequestProcessor();

  const mutationFn = async (email: string): Promise<{ method: "email" | "direct" }> => {
    const res = await api.post(`${getURL("REQUEST_PASSWORD_RESET")}`, { email });
    return res.data;
  };

  return mutate(["useRequestPasswordReset"], mutationFn, options);
};
