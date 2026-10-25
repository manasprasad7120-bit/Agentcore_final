import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface TagItem {
  id: string;
  name: string;
  category: string;
  description: string | null;
  is_predefined: boolean;
  usage_count?: number;
}

export const useGetPredefinedTags: useQueryFunctionType<
  undefined,
  TagItem[]
> = (options) => {
  const { query } = UseRequestProcessor();

  const responseFn = async () => {
    const { data } = await api.get<TagItem[]>(
      `${getURL("TAGS")}/predefined`,
    );
    return data;
  };

  return query(["useGetPredefinedTags"], responseFn, {
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
    ...options,
  });
};
