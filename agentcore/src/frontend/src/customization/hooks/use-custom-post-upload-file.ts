import { usePostUploadFileV2 } from "@/controllers/API/queries/file-management";
import type { useMutationFunctionType } from "@/types/api";

interface IPostUploadFile {
  file: File;
  knowledgeBaseName?: string;
  visibility?: string;
  public_scope?: "organization" | "department";
  org_id?: string;
  dept_id?: string;
  public_dept_ids?: string[];
}

export const customPostUploadFileV2: useMutationFunctionType<
  undefined,
  IPostUploadFile
> = (options?) => {
  return usePostUploadFileV2(options);
};
