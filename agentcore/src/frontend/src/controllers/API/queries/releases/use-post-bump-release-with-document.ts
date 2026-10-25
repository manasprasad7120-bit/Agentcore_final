import type { UseMutationResult } from "@tanstack/react-query";
import { useDarkStore } from "@/stores/darkStore";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { ReleaseRecord } from "./use-get-releases";

export type ReleaseBumpWithDocumentPayload = {
  bump_type: "major" | "minor" | "patch";
  release_notes?: string;
  document_file: File;
  regionCode?: string | null;
};

export const usePostBumpReleaseWithDocument = (options?: any) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const bumpReleaseWithDocumentFn = async (
    payload: ReleaseBumpWithDocumentPayload,
  ): Promise<ReleaseRecord> => {
    const body = new FormData();
    body.append("bump_type", payload.bump_type);
    if (payload.release_notes?.trim()) {
      body.append("release_notes", payload.release_notes.trim());
    }
    body.append("document_file", payload.document_file);

    const res = await api.post(`${getURL("RELEASES")}/bump-with-document`, body, {
      ...(payload.regionCode ? { headers: { "X-Region-Code": payload.regionCode } } : {}),
    });
    return res.data;
  };

  return mutate(["usePostBumpReleaseWithDocument"], bumpReleaseWithDocumentFn, {
    ...options,
    onSuccess: (data: ReleaseRecord, ...rest) => {
      if (data?.version) {
        useDarkStore.getState().refreshCurrentReleaseVersion(data.version);
      }
      options?.onSuccess?.(data, ...rest);
    },
    onSettled: (...args) => {
      queryClient.invalidateQueries({ queryKey: ["useGetCurrentRelease"] });
      queryClient.invalidateQueries({ queryKey: ["useGetReleases"] });
      options?.onSettled?.(...args);
    },
  }) as UseMutationResult<ReleaseRecord, any, ReleaseBumpWithDocumentPayload>;
};
