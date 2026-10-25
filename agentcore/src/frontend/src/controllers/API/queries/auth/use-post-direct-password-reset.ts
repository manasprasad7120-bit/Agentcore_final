// ---- DIRECT RESET FALLBACK (remove this file when SMTP is ready on client) ----
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useDirectPasswordReset = (options?: any) => {
  const { mutate } = UseRequestProcessor();

  const mutationFn = async ({
    email,
    new_password,
  }: {
    email: string;
    new_password: string;
  }): Promise<{ message: string }> => {
    const res = await api.post(`${getURL("DIRECT_PASSWORD_RESET")}`, { email, new_password });
    return res.data;
  };

  return mutate(["useDirectPasswordReset"], mutationFn, options);
};
// ---- END DIRECT RESET FALLBACK ----
