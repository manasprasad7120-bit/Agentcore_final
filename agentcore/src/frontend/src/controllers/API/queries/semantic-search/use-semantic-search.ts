import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../api";
import { getURL } from "../../helpers/constants";

export interface SemanticSearchParams {
  entity_type: "projects" | "agents" | "models";
  q: string;
  top_k?: number;
  registry_only?: boolean;
}

export interface SemanticSearchResultItem {
  id: string;
  name: string;
  description?: string | null;
  score: number;
  tags?: string[] | null;
  provider?: string;
  model_name?: string;
  model_type?: string;
}

export interface SemanticSearchResponse {
  results: SemanticSearchResultItem[];
  entity_type: string;
  query: string;
  count: number;
}

/**
 * Debounced semantic search hook.
 * Waits 400ms after the user stops typing before firing the API call.
 * Returns `isLoading` for showing a spinner.
 */
export const useSemanticSearch = (
  params: SemanticSearchParams | null,
  options?: { enabled?: boolean },
) => {
  const [debouncedQuery, setDebouncedQuery] = useState(params?.q ?? "");

  // Debounce the query — wait 400ms after user stops typing
  useEffect(() => {
    const query = params?.q ?? "";
    if (!query) {
      setDebouncedQuery("");
      return;
    }
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [params?.q]);

  return useQuery<SemanticSearchResponse>({
    queryKey: [
      "semantic-search",
      params?.entity_type,
      debouncedQuery,
      params?.top_k,
      params?.registry_only,
    ],
    queryFn: async () => {
      if (!debouncedQuery) {
        return { results: [], entity_type: params?.entity_type ?? "", query: "", count: 0 };
      }
      const queryParams: Record<string, unknown> = {
        entity_type: params!.entity_type,
        q: debouncedQuery,
        top_k: params?.top_k ?? 20,
      };
      if (params?.registry_only) {
        queryParams.registry_only = true;
      }
      const res = await api.get<SemanticSearchResponse>(
        `${getURL("SEMANTIC_SEARCH")}`,
        { params: queryParams },
      );
      return res.data;
    },
    enabled: options?.enabled !== false && !!debouncedQuery && debouncedQuery.length > 0,
    staleTime: 60000, // Cache results for 60s
    gcTime: 300000, // Keep in cache for 5 minutes
  });
};
