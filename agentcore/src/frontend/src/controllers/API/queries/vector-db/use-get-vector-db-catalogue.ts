import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface VectorDBInfo {
  id: string;
  name: string;
  description: string;
  provider: string;
  deployment: string;
  dimensions: string;
  indexType: string;
  status: string;
  vectorCount: string;
  isCustom: boolean;
  org_id?: string | null;
  dept_id?: string | null;
  // Pinecone tracking fields
  environment: string;
  indexName: string;
  namespace: string;
  agentId?: string | null;
  agentName: string;
  sourceEntryId?: string | null;
  migrationStatus: string;
  migratedAt?: string | null;
  vectorsCopied: number;
}

interface UseGetVectorDBCatalogueParams {
  environment?: string;
}

export const useGetVectorDBCatalogue: useQueryFunctionType<
  UseGetVectorDBCatalogueParams,
  VectorDBInfo[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getVectorDBCatalogueFn = async (): Promise<VectorDBInfo[]> => {
    const queryParams = new URLSearchParams();
    if (params?.environment && params.environment !== "all") {
      queryParams.set("environment", params.environment);
    }
    const qs = queryParams.toString();
    const url = `${getURL("VECTOR_DB_CATALOGUE")}/${qs ? `?${qs}` : ""}`;
    const res = await api.get(url);
    return res.data ?? [];
  };

  const queryResult: UseQueryResult<VectorDBInfo[], any> = query(
    ["useGetVectorDBCatalogue", params?.environment ?? "all"],
    getVectorDBCatalogueFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
