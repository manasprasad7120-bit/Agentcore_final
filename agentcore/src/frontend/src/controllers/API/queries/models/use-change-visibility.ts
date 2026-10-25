import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { ModelType } from "@/types/models/models";

interface ChangeVisibilityPayload {
  id: string;
  visibility_scope: string;
  org_id?: string | null;
  dept_id?: string | null;
  public_dept_ids?: string[] | null;
}

export const useChangeModelVisibility = () => {
  const queryClient = useQueryClient();

  return useMutation<ModelType, Error, ChangeVisibilityPayload>({
    mutationFn: async ({ id, visibility_scope, org_id, dept_id, public_dept_ids }) => {
      const response = await api.post(
        `api/models/registry/${id}/visibility`,
        { visibility_scope, org_id, dept_id, public_dept_ids },
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["registry-models"] });
    },
  });
};
