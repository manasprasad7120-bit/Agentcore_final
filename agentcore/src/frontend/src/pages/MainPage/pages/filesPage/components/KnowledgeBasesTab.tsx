import type { ColDef, SelectionChangedEvent } from "ag-grid-community";
import type { AgGridReact } from "ag-grid-react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Edit2 } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import TableComponent from "@/components/core/parameterRenderComponent/components/tableComponent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Loading from "@/components/ui/loading";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDeleteKnowledgeBase } from "@/controllers/API/queries/knowledge-bases/use-delete-knowledge-base";
import { useUpdateKBVisibility } from "@/controllers/API/queries/knowledge-bases/use-update-kb-visibility";
import {
  type KBVisibility,
  type KnowledgeBaseInfo,
  useGetKnowledgeBases,
} from "@/controllers/API/queries/knowledge-bases/use-get-knowledge-bases";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useGetFilesV2 } from "@/controllers/API/queries/file-management";
import { createFileUpload } from "@/helpers/create-file-upload";
import useUploadFile from "@/hooks/files/use-upload-file";
import BaseModal from "@/modals/baseModal";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import useFileSizeValidator from "@/shared/hooks/use-file-size-validator";
import useAlertStore from "@/stores/alertStore";
import { formatFileSize } from "@/utils/stringManipulation";
import { FILE_ICONS } from "@/utils/styleUtils";
import { cn } from "@/utils/utils";
import { AuthContext } from "@/contexts/authContext";
import KnowledgeBaseEmptyState from "./KnowledgeBaseEmptyState";
import KnowledgeBaseSelectionOverlay from "./KnowledgeBaseSelectionOverlay";

interface KnowledgeBasesTabProps {
  quickFilterText: string;
  setQuickFilterText: (text: string) => void;
  selectedFiles: any[];
  setSelectedFiles: (files: any[]) => void;
  quantitySelected: number;
  setQuantitySelected: (quantity: number) => void;
  isShiftPressed: boolean;
}

type DisplayRow = {
  id: string;
  name: string;
  rowType: "kb" | "file";
  // KB fields
  visibility?: string;
  created_by?: string;
  created_by_email?: string | null;
  is_own_kb?: boolean;
  updated_by?: string | null;
  updated_by_email?: string | null;
  department_name?: string | null;
  organization_name?: string | null;
  size?: number;
  file_count?: number;
  last_activity?: string | null;
  can_delete?: boolean;
  can_edit?: boolean;
  org_id?: string | null;
  dept_id?: string | null;
  public_dept_ids?: string[] | null;
  // File fields
  path?: string;
  updated_at?: string;
  created_at?: string;
  // For linking files to their KB
  kbId?: string;
  kbName?: string;
};

type VisibilityScope = "private" | "department" | "organization";

const KnowledgeBasesTab = ({
  quickFilterText,
  setQuickFilterText,
  selectedFiles,
  setSelectedFiles,
  quantitySelected,
  setQuantitySelected,
  isShiftPressed,
}: KnowledgeBasesTabProps) => {
  const { t } = useTranslation();
  const tableRef = useRef<AgGridReact<any>>(null);
  const { setErrorData, setSuccessData } = useAlertStore((state) => ({
    setErrorData: state.setErrorData,
    setSuccessData: state.setSuccessData,
  }));

  const { role, userData, permissions } = useContext(AuthContext);
  const normalizedRole = (role || userData?.role || "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const canAddKnowledge = permissions?.includes("add_new_knowledge") ?? false;
  // Show creator / modifier on every KB row regardless of role. Email is
  // still gated by role on the backend (devs / business users only see the
  // display name in the cell, and the email tooltip is empty for them).
  const showCreatedBy = true;
  const showDepartment = normalizedRole === "super_admin";
  const canMultiDept = normalizedRole === "super_admin" || normalizedRole === "root";
  const userDeptId = userData?.department_id ?? null;

  const getKbDeptIds = (kb: KnowledgeBaseInfo) => {
    const ids = new Set<string>();
    (kb.public_dept_ids || []).forEach((id) => ids.add(id));
    if (kb.dept_id) ids.add(kb.dept_id);
    return Array.from(ids);
  };

  const isMultiDeptKB = (kb: KnowledgeBaseInfo) =>
    kb.visibility === "DEPARTMENT" && getKbDeptIds(kb).length > 1;

  const isDeptScopedForUser = (kb: KnowledgeBaseInfo) =>
    Boolean(userDeptId && getKbDeptIds(kb).includes(userDeptId));

  const canEditKB = (kb: KnowledgeBaseInfo) => {
    if (normalizedRole === "root") {
      return kb.created_by === userData?.id && !kb.org_id && !kb.dept_id;
    }
    if (normalizedRole === "super_admin") return true;
    if (normalizedRole === "department_admin") {
      if (isMultiDeptKB(kb)) return false;
      if (kb.visibility === "ORGANIZATION") return false;
      if (kb.visibility === "DEPARTMENT") return isDeptScopedForUser(kb);
      if (kb.visibility === "PRIVATE") return isDeptScopedForUser(kb);
      return false;
    }
    if (normalizedRole === "developer" || normalizedRole === "business_user") {
      return kb.visibility === "PRIVATE" && kb.created_by === userData?.id;
    }
    return false;
  };

  const canDeleteKB = (kb: KnowledgeBaseInfo) => {
    if (normalizedRole === "root") {
      return kb.created_by === userData?.id && !kb.org_id && !kb.dept_id;
    }
    if (normalizedRole === "super_admin") return true;
    if (normalizedRole === "department_admin") {
      if (isMultiDeptKB(kb)) return false;
      if (kb.visibility === "ORGANIZATION") return false;
      if (kb.visibility === "DEPARTMENT") return isDeptScopedForUser(kb);
      if (kb.visibility === "PRIVATE") return isDeptScopedForUser(kb);
      return false;
    }
    if (normalizedRole === "developer" || normalizedRole === "business_user") {
      return kb.visibility === "PRIVATE" && kb.created_by === userData?.id;
    }
    return false;
  };

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [knowledgeBaseToDelete, setKnowledgeBaseToDelete] =
    useState<KnowledgeBaseInfo | null>(null);
  const [fileToDelete, setFileToDelete] = useState<DisplayRow | null>(null);
  const [isFileDeleteModalOpen, setIsFileDeleteModalOpen] = useState(false);
  const [isEditVisibilityModalOpen, setIsEditVisibilityModalOpen] = useState(false);
  const [knowledgeBaseToEdit, setKnowledgeBaseToEdit] = useState<KnowledgeBaseInfo | null>(null);

  // Upload modal state
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [knowledgeBaseName, setKnowledgeBaseName] = useState("");
  const [isExistingKB, setIsExistingKB] = useState(false);
  const [visibilityScope, setVisibilityScope] =
    useState<VisibilityScope>("private");
  const [selectedVisibility, setSelectedVisibility] = useState<KBVisibility>("PRIVATE");
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [selectedDeptIds, setSelectedDeptIds] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<{
    organizations: { id: string; name: string }[];
    departments: { id: string; name: string; org_id: string }[];
  }>({ organizations: [], departments: [] });
  const departmentsForSelectedOrg = useMemo(
    () =>
      visibilityOptions.departments.filter(
        (dept) => !selectedOrgId || dept.org_id === selectedOrgId,
      ),
    [visibilityOptions.departments, selectedOrgId],
  );
  const deptNameMap = useMemo(
    () => new Map(visibilityOptions.departments.map((dept) => [dept.id, dept.name])),
    [visibilityOptions.departments],
  );
  const selectedDeptLabel = useMemo(() => {
    const selectedIds = canMultiDept
      ? selectedDeptIds
      : selectedDeptId
        ? [selectedDeptId]
        : [];
    if (selectedIds.length === 0) return t("Select departments");
    const names = selectedIds.map((id) => deptNameMap.get(id)).filter(Boolean) as string[];
    if (names.length === 0) {
      return selectedIds.length > 1
        ? t("{{count}} departments", { count: selectedIds.length })
        : t("Select departments");
    }
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [canMultiDept, deptNameMap, selectedDeptId, selectedDeptIds, t]);
  const [pendingUploadFiles, setPendingUploadFiles] = useState<File[]>([]);
  // Tracks an in-flight upload so we can show a spinner on the Upload button
  // and block double-submits / modal dismissal while the request is running.
  const [isUploading, setIsUploading] = useState(false);
  const { validateFileSize } = useFileSizeValidator();
  const uploadFile = useUploadFile({ multiple: true });

  // Expandable rows state
  const [expandedKBs, setExpandedKBs] = useState<Record<string, boolean>>({});

  const queryClient = useQueryClient();
  const { data: knowledgeBases, isLoading, error } = useGetKnowledgeBases();
  const { data: files } = useGetFilesV2();
  const [isDeletingFile, setIsDeletingFile] = useState(false);
  const showActions = (knowledgeBases ?? []).some((kb) => canEditKB(kb));
  const updateVisibilityMutation = useUpdateKBVisibility(
    { kb_id: knowledgeBaseToEdit?.id || "" },
    {
      onSuccess: () => {
        setSuccessData({ title: t("Knowledge base visibility updated successfully") });
        setIsEditVisibilityModalOpen(false);
        setKnowledgeBaseToEdit(null);
      },
      onError: (error: any) => {
        setErrorData({
          title: t("Failed to update visibility"),
          list: [error?.response?.data?.detail || t("Unexpected error")],
        });
      },
    },
  );

  const deleteKnowledgeBaseMutation = useDeleteKnowledgeBase(
    {
      kb_name: knowledgeBaseToDelete?.id || "",
    },
    {
      onSuccess: () => {
        setSuccessData({
          title: t('Knowledge Base "{{name}}" deleted successfully!', {
            name: knowledgeBaseToDelete?.name,
          }),
        });
        queryClient.invalidateQueries({ queryKey: ["useGetFilesV2"] });
        resetDeleteState();
      },
      onError: (error: any) => {
        setErrorData({
          title: t("Failed to delete knowledge base"),
          list: [
            error?.response?.data?.detail ||
              error?.message ||
              t("An unknown error occurred"),
          ],
        });
        resetDeleteState();
      },
    },
  );

  if (error) {
    setErrorData({
      title: "Failed to load knowledge bases",
      list: [error?.message || "An unknown error occurred"],
    });
  }

  const resetDeleteState = () => {
    setKnowledgeBaseToDelete(null);
    setIsDeleteModalOpen(false);
  };

  const handleDelete = (knowledgeBase: KnowledgeBaseInfo) => {
    setKnowledgeBaseToDelete(knowledgeBase);
    setIsDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    if (knowledgeBaseToDelete && !deleteKnowledgeBaseMutation.isPending) {
      deleteKnowledgeBaseMutation.mutate();
    }
  };

  const handleDeleteFile = (file: DisplayRow) => {
    setFileToDelete(file);
    setIsFileDeleteModalOpen(true);
  };

  const openEditVisibilityModal = (kb: KnowledgeBaseInfo) => {
    setKnowledgeBaseToEdit(kb);
    const kbVisibility = (kb.visibility as KBVisibility) || "PRIVATE";
    setSelectedVisibility(kbVisibility);
    setVisibilityScope(
      kbVisibility === "PRIVATE"
        ? "private"
        : kbVisibility === "ORGANIZATION"
          ? "organization"
          : "department",
    );
    setSelectedOrgId(kb.org_id || "");
    setSelectedDeptId(kb.dept_id || "");
    const deptIds = kb.public_dept_ids?.length
      ? kb.public_dept_ids
      : kb.dept_id
        ? [kb.dept_id]
        : [];
    setSelectedDeptIds(deptIds);
    setIsEditVisibilityModalOpen(true);
  };

  const confirmDeleteFile = async () => {
    if (!fileToDelete || isDeletingFile) return;
    setIsDeletingFile(true);
    try {
      await api.delete(
        `${getURL("FILE_MANAGEMENT", { id: fileToDelete.id }, true)}`,
      );
      setSuccessData({
        title: t('File "{{name}}" deleted successfully!', { name: fileToDelete.name }),
      });
      queryClient.invalidateQueries({ queryKey: ["useGetFilesV2"] });
      queryClient.invalidateQueries({ queryKey: ["useGetKnowledgeBases"] });
    } catch (error: any) {
      setErrorData({
        title: t("Failed to delete file"),
        list: [
          error?.response?.data?.detail ||
            error?.message ||
            t("An unknown error occurred"),
        ],
      });
    } finally {
      setIsDeletingFile(false);
      setFileToDelete(null);
      setIsFileDeleteModalOpen(false);
    }
  };

  const handleSelectionChange = (event: SelectionChangedEvent) => {
    const selectedRows = event.api.getSelectedRows();
    setSelectedFiles(selectedRows);
    if (selectedRows.length > 0) {
      setQuantitySelected(selectedRows.length);
    } else {
      setTimeout(() => {
        setQuantitySelected(0);
      }, 300);
    }
  };

  useEffect(() => {
    if (!isUploadModalOpen) {
      setPendingUploadFiles([]);
      setKnowledgeBaseName("");
      setVisibilityScope("private");
      setSelectedVisibility("PRIVATE");
      setSelectedOrgId("");
      setSelectedDeptId("");
      setSelectedDeptIds([]);
      setIsExistingKB(false);
    }
  }, [isUploadModalOpen]);

  useEffect(() => {
    if (!showDepartment && !canMultiDept) return;
    if (visibilityOptions.organizations.length || visibilityOptions.departments.length) return;
    api.get(`${getURL("KNOWLEDGE_BASES")}/visibility-options`).then((res) => {
      const options = res.data || { organizations: [], departments: [] };
      setVisibilityOptions(options);
    });
  }, [showDepartment, canMultiDept, visibilityOptions.organizations.length, visibilityOptions.departments.length]);

  useEffect(() => {
    if ((!isUploadModalOpen || isExistingKB) && !isEditVisibilityModalOpen) return;
    api.get(`${getURL("KNOWLEDGE_BASES")}/visibility-options`).then((res) => {
      const options = res.data || { organizations: [], departments: [] };
      setVisibilityOptions(options);
      setSelectedOrgId((prev) => prev || options.organizations?.[0]?.id || "");
      setSelectedDeptId((prev) => prev || options.departments?.[0]?.id || "");
      setSelectedDeptIds((prev) => (prev.length > 0 ? prev : options.departments?.[0]?.id ? [options.departments[0].id] : []));
    });
  }, [isUploadModalOpen, isExistingKB, isEditVisibilityModalOpen]);

  useEffect(() => {
    setSelectedVisibility(
      visibilityScope === "private"
        ? "PRIVATE"
        : visibilityScope === "organization"
          ? "ORGANIZATION"
          : "DEPARTMENT",
    );
  }, [visibilityScope]);

  useEffect(() => {
    if (visibilityScope === "organization") {
      if (!selectedOrgId && visibilityOptions.organizations.length > 0) {
        setSelectedOrgId(visibilityOptions.organizations[0].id);
      }
      return;
    }
    if (visibilityScope === "department") {
      if (normalizedRole === "super_admin" || normalizedRole === "root") {
        if (!selectedOrgId && visibilityOptions.organizations.length > 0) {
          setSelectedOrgId(visibilityOptions.organizations[0].id);
        }
        if (selectedDeptIds.length === 0 && visibilityOptions.departments.length > 0) {
          const dept =
            visibilityOptions.departments.find(
              (d) => !selectedOrgId || d.org_id === selectedOrgId,
            ) ?? visibilityOptions.departments[0];
          if (dept) {
            setSelectedDeptIds([dept.id]);
            setSelectedDeptId(dept.id);
            if (!selectedOrgId) setSelectedOrgId(dept.org_id);
          }
        }
        return;
      }
      if (!selectedDeptId && visibilityOptions.departments.length > 0) {
        const dept = visibilityOptions.departments[0];
        setSelectedDeptId(dept.id);
        setSelectedDeptIds([dept.id]);
        if (!selectedOrgId) setSelectedOrgId(dept.org_id);
      }
    }
  }, [
    visibilityScope,
    normalizedRole,
    selectedOrgId,
    selectedDeptId,
    selectedDeptIds.length,
    visibilityOptions.organizations,
    visibilityOptions.departments,
  ]);

  const handleUpload = async (
    uploadFiles?: File[],
    kbName?: string,
    visibility?: string,
    scope?: {
      org_id?: string;
      dept_id?: string;
      public_dept_ids?: string[];
    },
  ) => {
    if (!canAddKnowledge) {
      setErrorData({
        title: t("Access denied"),
        list: [t("You do not have permission to add knowledge bases.")],
      });
      return;
    }
    try {
      const filesIds = await uploadFile({
        files: uploadFiles,
        knowledgeBaseName: kbName,
        visibility,
        org_id: scope?.org_id,
        dept_id: scope?.dept_id,
        public_dept_ids: scope?.public_dept_ids,
      });
      setSuccessData({
        title: t(`File${filesIds.length > 1 ? "s" : ""} uploaded successfully`),
      });
    } catch (error: any) {
      setErrorData({
        title: t("Error uploading file"),
        list: [error.message || t("An error occurred while uploading the file")],
      });
    }
  };

  const handleOpenUploadModal = () => {
    if (!canAddKnowledge) {
      setErrorData({
        title: t("Access denied"),
        list: [t("You do not have permission to add knowledge bases.")],
      });
      return;
    }
    setIsExistingKB(false);
    setKnowledgeBaseName("");
    setVisibilityScope("private");
    setSelectedVisibility("PRIVATE");
    setSelectedOrgId("");
    setSelectedDeptId("");
    setSelectedDeptIds([]);
    setIsUploadModalOpen(true);
  };

  const handleUploadMoreToKB = (kb: KnowledgeBaseInfo) => {
    if (!canAddKnowledge) {
      setErrorData({
        title: t("Access denied"),
        list: [t("You do not have permission to add knowledge bases.")],
      });
      return;
    }
    setIsExistingKB(true);
    setKnowledgeBaseName(kb.name);
    setSelectedVisibility((kb.visibility as KBVisibility) || "PRIVATE");
    setIsUploadModalOpen(true);
  };

  const handleChooseFiles = async () => {
    if (!canAddKnowledge) {
      setErrorData({
        title: t("Access denied"),
        list: [t("You do not have permission to add knowledge bases.")],
      });
      return;
    }
    try {
      const selected = await createFileUpload({
        multiple: true,
        accept: "",
      });
      const validFiles: File[] = [];
      for (const file of selected) {
        validateFileSize(file);
        validFiles.push(file);
      }
      setPendingUploadFiles((prev) => [...prev, ...validFiles]);
    } catch (error: any) {
      setErrorData({
        title: t("Error selecting files"),
        list: [error.message || t("Could not select files")],
      });
    }
  };

  const removeFile = (index: number) => {
    setPendingUploadFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const clearSelection = () => {
    setQuantitySelected(0);
    setSelectedFiles([]);
  };

  // Helper to extract KB name from file path
  const getKBNameFromPath = (path: string) => {
    const normalizedPath = path.replace(/\\/g, "/");
    const segments = normalizedPath.split("/").filter(Boolean);
    // Legacy: <user_id>/<kb_name>/<file>
    // New:    <user_id>/<kb_id>/<kb_name>/<file>
    if (segments.length >= 4) return segments[2];
    if (segments.length >= 3) return segments[1];
    return null;
  };

  // Build display rows: KB rows + expandable file rows
  const displayRows: DisplayRow[] = useMemo(() => {
    if (!knowledgeBases || !Array.isArray(knowledgeBases)) return [];

    const filesByKBId = new Map<string, any[]>();
    const filesByKBName = new Map<string, any[]>();
    if (files && Array.isArray(files)) {
      files.forEach((file: any) => {
        if (file.knowledge_base_id) {
          const existingById = filesByKBId.get(file.knowledge_base_id) ?? [];
          existingById.push(file);
          filesByKBId.set(file.knowledge_base_id, existingById);
        }
        const kbName = getKBNameFromPath(file.path);
        if (kbName) {
          const existingByName = filesByKBName.get(kbName) ?? [];
          existingByName.push(file);
          filesByKBName.set(kbName, existingByName);
        }
      });
    }

    const rows: DisplayRow[] = [];
    knowledgeBases.forEach((kb) => {
      const canDelete = canDeleteKB(kb);
      const canEdit = canEditKB(kb);
      rows.push({
        id: kb.id,
        name: kb.name,
        rowType: "kb",
        visibility: kb.visibility,
        created_by: kb.created_by,
        created_by_email: kb.created_by_email,
        is_own_kb: (kb as any).is_own_kb,
        updated_by: (kb as any).updated_by,
        updated_by_email: (kb as any).updated_by_email,
        department_name: kb.department_name,
        organization_name: kb.organization_name,
        org_id: kb.org_id,
        dept_id: kb.dept_id,
        public_dept_ids: kb.public_dept_ids,
        size: kb.size,
        file_count: kb.file_count,
        last_activity: kb.last_activity ?? kb.updated_at ?? null,
        can_delete: canDelete,
        can_edit: canEdit,
      });

      if (expandedKBs[kb.id]) {
        const kbFiles = filesByKBId.get(kb.id) ?? filesByKBName.get(kb.name) ?? [];
        kbFiles.forEach((file) => {
          rows.push({
            id: file.id,
            name: file.name,
            rowType: "file",
            path: file.path,
            size: file.size,
            updated_at: file.updated_at,
            created_at: file.created_at,
            kbId: kb.id,
            kbName: kb.name,
            can_delete: canDelete,
          });
        });
      }
    });

    return rows;
  }, [knowledgeBases, files, expandedKBs, userData?.id]);

  const formatDepartmentScope = (row: DisplayRow) => {
    if (row.rowType !== "kb") return "";
    if (row.visibility === "ORGANIZATION") return t("All departments");
    const deptIds = new Set<string>();
    (row.public_dept_ids || []).forEach((id) => deptIds.add(id));
    if (row.dept_id) deptIds.add(row.dept_id);
    if (deptIds.size === 0) return "-";
    const names = Array.from(deptIds).map((id) => deptNameMap.get(id) || id);
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  };

  // Column definitions with expandable KB rows
  const columnDefs: ColDef[] = useMemo(() => {
    const baseCellClass =
      "text-muted-foreground cursor-pointer select-text group-[.no-select-cells]:cursor-default group-[.no-select-cells]:select-none";

    return [
      {
      headerName: t("Name"),
        field: "name",
        flex: 3,
        sortable: false,
        headerCheckboxSelection: true,
        checkboxSelection: (params: any) => params.data?.rowType === "kb",
        editable: false,
        filter: "agTextColumnFilter",
        cellClass: baseCellClass,
        cellRenderer: (params: any) => {
          if (params.data.rowType === "kb") {
            const isExpanded = expandedKBs[params.data.id];
            const fileCount = params.data.file_count ?? 0;
            return (
              <div className="flex w-full items-center justify-between">
                <div className="flex min-w-0 items-center gap-2 font-medium">
                  <button
                    className="flex shrink-0 items-center"
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedKBs((prev) => ({
                        ...prev,
                        [params.data.id]: !isExpanded,
                      }));
                    }}
                  >
                    <ForwardedIconComponent
                      name={isExpanded ? "ChevronDown" : "ChevronRight"}
                      className="h-4 w-4 shrink-0"
                    />
                  </button>
                  <ForwardedIconComponent
                    name="Folder"
                    className="h-4 w-4 shrink-0"
                  />
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className="truncate text-sm font-medium"
                      title={params.value}
                    >
                      {params.value}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      ({fileCount} {t(fileCount !== 1 ? "files" : "file")})
                    </span>
                  </div>
                </div>
                {canAddKnowledge ? (
                  <ShadTooltip content={t("Add files to this knowledge base")} side="left">
                    <button
                      className="ml-2 flex shrink-0 items-center rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      onClick={(e) => {
                        e.stopPropagation();
                        const kb = knowledgeBases?.find(
                          (k) => k.id === params.data.id,
                        );
                        if (kb) handleUploadMoreToKB(kb);
                      }}
                    >
                      <ForwardedIconComponent
                        name="Upload"
                        className="h-3.5 w-3.5"
                      />
                    </button>
                  </ShadTooltip>
                ) : (
                  <span className="ml-2 h-6 w-6" />
                )}
              </div>
            );
          }

          const type =
            params.data.path?.split(".").pop()?.toLowerCase() ?? "";
          const baseName =
            type && params.value?.toLowerCase().endsWith(`.${type}`)
              ? params.value.slice(0, -(type.length + 1))
              : params.value;
          const displayName = type ? `${baseName}.${type}` : params.value;
          return (
            <div className="flex w-full items-center justify-between">
              <div className="flex min-w-0 items-center gap-3 pl-10 font-medium">
                <ForwardedIconComponent
                  name={FILE_ICONS[type]?.icon ?? "File"}
                  className={cn(
                    "h-5 w-5 shrink-0",
                    FILE_ICONS[type]?.color ?? undefined,
                  )}
                />
                <span
                  className="truncate text-sm"
                  title={displayName}
                >
                  {displayName}
                </span>
              </div>
              <ShadTooltip content={t("Delete file")} side="left">
                {params.data?.can_delete ? (
                  <button
                    className="ml-2 flex items-center rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteFile(params.data);
                    }}
                  >
                    <ForwardedIconComponent
                      name="Trash2"
                      className="h-3.5 w-3.5"
                    />
                  </button>
                ) : (
                  <span className="ml-2 h-6 w-6" />
                )}
              </ShadTooltip>
            </div>
          );
        },
      },
      {
        headerName: t("Visibility"),
        field: "visibility",
        flex: 1,
        sortable: false,
        filter: "agTextColumnFilter",
        editable: false,
        cellClass: baseCellClass,
        valueGetter: (params: any) => {
          if (params.data?.rowType === "file") return "";
          const v = params.data?.visibility || "PRIVATE";
          const labels: Record<string, string> = {
            PRIVATE: t("Private"),
            DEPARTMENT: t("Department"),
            ORGANIZATION: t("Organization"),
          };
          return labels[v] || v;
        },
      },
      {
        headerName: t("Size"),
        field: "size",
        flex: 1,
        sortable: false,
        editable: false,
        cellClass: baseCellClass,
        valueFormatter: (params: any) => {
          if (params.value == null) return "";
          return formatFileSize(params.value);
        },
      },
      {
        headerName: t("Modified"),
        field: "last_activity",
        flex: 1,
        sortable: false,
        editable: false,
        cellClass: baseCellClass,
        valueFormatter: (params: any) => {
          const rawValue =
            params.data?.rowType === "kb"
              ? params.data?.last_activity
              : params.data?.updated_at;
          if (!rawValue) return "";
          const hasTimezone = /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(rawValue);
          return new Date(hasTimezone ? rawValue : `${rawValue}Z`).toLocaleString();
        },
      },
      ...(showCreatedBy
        ? [
            {
              headerName: t("Created By"),
              field: "created_by_email",
              flex: 1.2,
              sortable: false,
              editable: false,
              cellClass: baseCellClass,
              cellRenderer: (params: any) => {
                if (params.data?.rowType !== "kb") return "";
                const emailValue = params.data?.created_by_email || "";
                const rawCreatedBy = params.data?.created_by || "";
                const isOwnKb = !!params.data?.is_own_kb;
                const looksLikeUuid =
                  typeof rawCreatedBy === "string" &&
                  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(rawCreatedBy);
                const displayValue = isOwnKb
                  ? t("You")
                  : (!looksLikeUuid && rawCreatedBy) ||
                    (typeof emailValue === "string" && emailValue.includes("@")
                      ? emailValue.split("@")[0]
                      : emailValue) ||
                    "-";
                return (
                  <div className="max-w-[170px] truncate" title={emailValue || displayValue}>
                    {displayValue}
                  </div>
                );
              },
            } as ColDef,
            {
              headerName: t("Modified By"),
              field: "updated_by",
              flex: 1.2,
              sortable: false,
              editable: false,
              cellClass: baseCellClass,
              cellRenderer: (params: any) => {
                if (params.data?.rowType !== "kb") return "";
                const rawUpdatedBy = params.data?.updated_by || "";
                const updatedEmail = params.data?.updated_by_email || "";
                if (!rawUpdatedBy && !updatedEmail) {
                  return <div className="text-muted-foreground">-</div>;
                }
                const isSelf =
                  !!userData?.id &&
                  ((typeof rawUpdatedBy === "string" &&
                    rawUpdatedBy === userData.id) ||
                    (typeof updatedEmail === "string" &&
                      updatedEmail.toLowerCase() ===
                        String(userData.email || "").toLowerCase()));
                const looksLikeUuid =
                  typeof rawUpdatedBy === "string" &&
                  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(rawUpdatedBy);
                const displayValue = isSelf
                  ? t("You")
                  : (!looksLikeUuid && rawUpdatedBy) ||
                    (typeof updatedEmail === "string" && updatedEmail.includes("@")
                      ? updatedEmail.split("@")[0]
                      : updatedEmail) ||
                    "-";
                return (
                  <div
                    className="max-w-[170px] truncate"
                    title={updatedEmail || displayValue}
                  >
                    {displayValue}
                  </div>
                );
              },
            } as ColDef,
          ]
        : []),
      ...(showDepartment
        ? [
            {
              headerName: t("Department Scope"),
              headerTooltip: t("Department Scope"),
              field: "department_name",
              flex: 1.2,
              sortable: false,
              editable: false,
              cellClass: baseCellClass,
              valueGetter: (params: any) => {
                if (params.data?.rowType !== "kb") return "";
                return formatDepartmentScope(params.data);
              },
              tooltipValueGetter: (params: any) => {
                if (params.data?.rowType !== "kb") return "";
                return formatDepartmentScope(params.data);
              },
            } as ColDef,
          ]
        : []),
      ...(showActions
        ? [
            {
              headerName: t("Actions"),
              field: "actions",
              flex: 0.8,
              sortable: false,
              filter: false,
              editable: false,
              cellClass: baseCellClass,
              cellRenderer: (params: any) => {
                if (params.data?.rowType !== "kb") return "";
                const kb = knowledgeBases?.find((k) => k.id === params.data.id);
                if (!kb) return "";
                if (!params.data?.can_edit) {
                  return (
                    <div className="flex h-full items-center">
                      <span className="text-xs text-muted-foreground">-</span>
                    </div>
                  );
                }
                return (
                  <div className="flex h-full items-center">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2"
                      onClick={(e) => {
                        e.stopPropagation();
                        openEditVisibilityModal(kb);
                      }}
                    >
                      <Edit2 className="mr-2 h-4 w-4" />
                      {t("Edit")}
                    </Button>
                  </div>
                );
              },
            } as ColDef,
          ]
        : []),
    ];
  }, [
    expandedKBs,
    knowledgeBases,
    showActions,
    showCreatedBy,
    showDepartment,
    deptNameMap,
  ]);

  if (isLoading || !knowledgeBases || !Array.isArray(knowledgeBases)) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Loading />
      </div>
    );
  }

  const uploadModal = (
    <BaseModal
      size="small-h-full"
      open={isUploadModalOpen}
      setOpen={(next) => {
        // Don't let the user dismiss the modal mid-upload â the underlying
        // request is still in flight and another click would re-trigger it.
        if (isUploading && !next) return;
        setIsUploadModalOpen(next);
      }}
    >
      <BaseModal.Header
        description={
          isExistingKB
        ? t('Add more files to "{{name}}"', { name: knowledgeBaseName })
            : t("Create a new knowledge base by uploading files.")
        }
      >
        {isExistingKB ? t("Add Files") : t("Upload Knowledge Base")}
      </BaseModal.Header>
      <BaseModal.Content className="min-h-0 max-h-[70vh] overflow-y-auto">
        <div className="flex flex-col gap-4 px-1">
          {/* KB Name */}
          <div className="space-y-1.5">
            <Label className="text-sm font-medium">{t("Knowledge Base Name")}</Label>
            <Input
              placeholder={t("Enter knowledge base name")}
              value={knowledgeBaseName}
              onChange={(event) => {
                setKnowledgeBaseName(event.target.value);
              }}
              disabled={isExistingKB}
              data-testid="knowledge-base-name-upload-input"
            />
          </div>

          {/* Visibility */}
          {!isExistingKB && (
            <div className="space-y-1.5">
              <Label className="text-sm font-medium">{t("Visibility Scope")}</Label>
              <Select
                value={visibilityScope}
                onValueChange={(value) => setVisibilityScope(value as VisibilityScope)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("Select visibility")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">{t("Private")}</SelectItem>
                  <SelectItem value="department">{t("Department")}</SelectItem>
                  <SelectItem value="organization">{t("Organization")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {!isExistingKB && visibilityScope === "organization" && (
            <div className="space-y-1.5">
              <Label className="text-sm font-medium">{t("Organization")}</Label>
              <Select
                value={selectedOrgId}
                onValueChange={setSelectedOrgId}
                disabled={
                  normalizedRole === "developer" ||
                  normalizedRole === "department_admin" ||
                  normalizedRole === "business_user"
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("Select organization")} />
                </SelectTrigger>
                <SelectContent>
                  {visibilityOptions.organizations.map((org) => (
                    <SelectItem key={org.id} value={org.id}>
                      {org.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {!isExistingKB && visibilityScope === "department" && (
            <>
              {canMultiDept && (
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium">{t("Organization")}</Label>
                  <Select
                    value={selectedOrgId}
                    onValueChange={(value) => {
                      setSelectedOrgId(value);
                      setSelectedDeptId("");
                      setSelectedDeptIds([]);
                    }}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder={t("Select organization")} />
                    </SelectTrigger>
                    <SelectContent>
                      {visibilityOptions.organizations.map((org) => (
                        <SelectItem key={org.id} value={org.id}>
                          {org.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div className="space-y-1.5">
                <Label className="text-sm font-medium">
                  {canMultiDept ? t("Departments") : t("Department")}
                </Label>
                {canMultiDept ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full justify-between font-normal"
                      >
                        <span className="truncate text-left">{selectedDeptLabel}</span>
                        <ChevronDown className="ml-2 h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="max-h-64 w-[340px] overflow-auto">
                      {departmentsForSelectedOrg.map((dept) => (
                        <DropdownMenuCheckboxItem
                          key={dept.id}
                          checked={selectedDeptIds.includes(dept.id)}
                          onSelect={(event) => event.preventDefault()}
                          onCheckedChange={(checked) => {
                            setSelectedDeptIds((prev) =>
                              checked
                                ? Array.from(new Set([...prev, dept.id]))
                                : prev.filter((id) => id !== dept.id),
                            );
                          }}
                        >
                          {dept.name}
                        </DropdownMenuCheckboxItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  <Select
                    value={selectedDeptId}
                    onValueChange={(value) => {
                      setSelectedDeptId(value);
                      setSelectedDeptIds(value ? [value] : []);
                      const dept = visibilityOptions.departments.find((d) => d.id === value);
                      if (dept) setSelectedOrgId(dept.org_id);
                    }}
                    disabled
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder={t("Select department")} />
                    </SelectTrigger>
                    <SelectContent>
                      {visibilityOptions.departments.map((dept) => (
                        <SelectItem key={dept.id} value={dept.id}>
                          {dept.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            </>
          )}

          {/* File selection area */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-sm font-medium">{t("Files")}</Label>
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={handleChooseFiles}
                disabled={!canAddKnowledge}
              >
                <ForwardedIconComponent name="Plus" className="mr-1 h-3.5 w-3.5" />
                {t("Choose Files")}
              </Button>
            </div>

            {pendingUploadFiles.length === 0 ? (
              <div
                className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/25 px-6 py-8 text-center transition-colors hover:border-muted-foreground/50"
                onClick={handleChooseFiles}
              >
                <ForwardedIconComponent
                  name="Upload"
                  className="mb-2 h-8 w-8 text-muted-foreground/50"
                />
                <p className="text-sm text-muted-foreground">
                  {t("Click to select files or use the button above")}
                </p>
              </div>
            ) : (
              <div className="max-h-52 overflow-auto rounded-lg border">
                <div className="flex flex-col divide-y">
                  {pendingUploadFiles.map((file, index) => {
                    const fileType =
                      file.name.split(".").pop()?.toLowerCase() ?? "";
                    const fileIcon = FILE_ICONS[fileType]?.icon ?? "File";
                    const fileIconColor =
                      FILE_ICONS[fileType]?.color ?? "text-muted-foreground";

                    return (
                      <div
                        key={`${file.name}-${file.size}-${index}`}
                        className="flex items-center justify-between px-3 py-2"
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          <ForwardedIconComponent
                            name={fileIcon}
                            className={cn("h-4 w-4 shrink-0", fileIconColor)}
                          />
                          <span className="truncate text-sm font-medium">
                            {file.name}
                          </span>
                        </div>
                        <div className="ml-3 flex shrink-0 items-center gap-2">
                          <span className="rounded bg-muted px-1.5 py-0.5 text-xxs uppercase text-muted-foreground">
                            {fileType || t("file")}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {formatFileSize(file.size)}
                          </span>
                          <button
                            className="ml-1 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-destructive"
                            onClick={() => removeFile(index)}
                          >
                            <ForwardedIconComponent
                              name="X"
                              className="h-3.5 w-3.5"
                            />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {pendingUploadFiles.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {t("{{count}} file(s) selected", { count: pendingUploadFiles.length })}
                {" \u00B7 "}
                {formatFileSize(
                  pendingUploadFiles.reduce((acc, f) => acc + f.size, 0),
                )}{" "}
                {t("total")}
              </p>
            )}
          </div>
        </div>
      </BaseModal.Content>
      <BaseModal.Footer
        submit={{
          label: isExistingKB ? t("Upload Files") : t("Upload Knowledge Base"),
          dataTestId: "upload-files-with-kb-button",
          loading: isUploading,
          disabled:
            isUploading ||
            !canAddKnowledge ||
            pendingUploadFiles.length === 0 ||
            !knowledgeBaseName.trim() ||
            (visibilityScope === "organization" && !selectedOrgId) ||
            (visibilityScope === "department" &&
              ((canMultiDept && selectedDeptIds.length === 0) ||
                (!canMultiDept && !selectedDeptId))),
          onClick: async () => {
            if (isUploading) return;
            const kbName = knowledgeBaseName.trim();
            if (!kbName) {
              setErrorData({
                title: t("Knowledge base name is required"),
              });
              return;
            }
            const deptIds = canMultiDept
              ? selectedDeptIds
              : selectedDeptId
                ? [selectedDeptId]
                : [];
            const deptId = deptIds.length === 1 ? deptIds[0] : undefined;
            const uploadScope =
              visibilityScope === "organization"
                ? { org_id: selectedOrgId }
                : visibilityScope === "department"
                  ? { org_id: selectedOrgId, dept_id: deptId, public_dept_ids: deptIds }
                  : undefined;
            setIsUploading(true);
            try {
              await handleUpload(
                pendingUploadFiles,
                kbName,
                selectedVisibility,
                uploadScope,
              );
              setIsUploadModalOpen(false);
            } finally {
              setIsUploading(false);
            }
          },
        }}
      >
        <></>
      </BaseModal.Footer>
    </BaseModal>
  );

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header - Fixed */}
      <div className="flex flex-shrink-0 flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("Knowledge Base")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Manage knowledge sources for agents")}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex w-full sm:w-64">
            <Input
              icon="Search"
              data-testid="search-kb-input"
              type="text"
              placeholder={t("Search knowledge bases...")}
              className="w-full"
              value={quickFilterText || ""}
              onChange={(event) => setQuickFilterText(event.target.value)}
            />
          </div>
          <Button
            className="flex items-center gap-2 font-semibold"
            onClick={handleOpenUploadModal}
            disabled={!canAddKnowledge}
          >
            <ForwardedIconComponent name="Plus" /> {t("Upload Knowledge Base")}
          </Button>
        </div>
      </div>

      <div className="flex h-full flex-col overflow-hidden p-4 sm:p-6">
        {knowledgeBases.length === 0 ? (
          <KnowledgeBaseEmptyState />
        ) : (
          <div className="relative h-full">
            <TableComponent
              rowHeight={45}
              headerHeight={45}
              cellSelection={false}
              tableOptions={{
                hide_options: true,
              }}
              suppressRowClickSelection={!isShiftPressed}
              rowSelection="multiple"
              onSelectionChanged={handleSelectionChange}
              columnDefs={columnDefs}
              rowData={displayRows}
              className={cn(
                "ag-no-border ag-knowledge-table group w-full",
                isShiftPressed && quantitySelected > 0 && "no-select-cells",
              )}
              pagination
              ref={tableRef}
              quickFilterText={quickFilterText}
              gridOptions={{
                stopEditingWhenCellsLoseFocus: true,
                ensureDomOrder: true,
                colResizeDefault: "shift",
                isRowSelectable: (params: any) =>
                  params.data?.rowType === "kb" && !!params.data?.can_delete,
              }}
            />

            <KnowledgeBaseSelectionOverlay
              selectedFiles={selectedFiles}
              quantitySelected={quantitySelected}
              onClearSelection={clearSelection}
            />
          </div>
        )}
      </div>

      <DeleteConfirmationModal
        open={isDeleteModalOpen}
        setOpen={setIsDeleteModalOpen}
        onConfirm={confirmDelete}
        description={`knowledge base "${knowledgeBaseToDelete?.name || ""}"`}
        note={t("This action cannot be undone")}
      >
        <></>
      </DeleteConfirmationModal>

      <DeleteConfirmationModal
        open={isFileDeleteModalOpen}
        setOpen={setIsFileDeleteModalOpen}
        onConfirm={confirmDeleteFile}
        description={`file "${fileToDelete?.name || ""}"`}
        note={t("This action cannot be undone")}
      >
        <></>
      </DeleteConfirmationModal>

      <BaseModal
        size="small-h-full"
        open={isEditVisibilityModalOpen}
        setOpen={setIsEditVisibilityModalOpen}
      >
        <BaseModal.Header description={t("Update visibility scope for this knowledge base.")}>
          {t("Edit Visibility")}
        </BaseModal.Header>
        <BaseModal.Content className="min-h-0 max-h-[70vh] overflow-y-auto">
          <div className="flex flex-col gap-4 px-1">
            <div className="space-y-1.5">
              <Label className="text-sm font-medium">{t("Visibility Scope")}</Label>
              <Select
                value={visibilityScope}
                onValueChange={(value) => setVisibilityScope(value as VisibilityScope)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("Select visibility")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">{t("Private")}</SelectItem>
                  <SelectItem value="department">{t("Department")}</SelectItem>
                  <SelectItem value="organization">{t("Organization")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {visibilityScope === "organization" && (
              <div className="space-y-1.5">
                <Label className="text-sm font-medium">{t("Organization")}</Label>
                <Select
                  value={selectedOrgId}
                  onValueChange={setSelectedOrgId}
                  disabled={
                    normalizedRole === "developer" ||
                    normalizedRole === "department_admin" ||
                    normalizedRole === "business_user"
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={t("Select organization")} />
                  </SelectTrigger>
                  <SelectContent>
                    {visibilityOptions.organizations.map((org) => (
                      <SelectItem key={org.id} value={org.id}>
                        {org.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {visibilityScope === "department" && (
              <>
                {canMultiDept && (
                  <div className="space-y-1.5">
                    <Label className="text-sm font-medium">{t("Organization")}</Label>
                    <Select
                      value={selectedOrgId}
                      onValueChange={(value) => {
                        setSelectedOrgId(value);
                        setSelectedDeptId("");
                        setSelectedDeptIds([]);
                      }}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("Select organization")} />
                      </SelectTrigger>
                      <SelectContent>
                        {visibilityOptions.organizations.map((org) => (
                          <SelectItem key={org.id} value={org.id}>
                            {org.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium">
                    {canMultiDept ? t("Departments") : t("Department")}
                  </Label>
                  {canMultiDept ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="outline"
                          className="w-full justify-between font-normal"
                        >
                          <span className="truncate text-left">{selectedDeptLabel}</span>
                          <ChevronDown className="ml-2 h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="max-h-64 w-[340px] overflow-auto">
                        {departmentsForSelectedOrg.map((dept) => (
                          <DropdownMenuCheckboxItem
                            key={dept.id}
                            checked={selectedDeptIds.includes(dept.id)}
                            onSelect={(event) => event.preventDefault()}
                            onCheckedChange={(checked) => {
                              setSelectedDeptIds((prev) =>
                                checked
                                  ? Array.from(new Set([...prev, dept.id]))
                                  : prev.filter((id) => id !== dept.id),
                              );
                            }}
                          >
                            {dept.name}
                          </DropdownMenuCheckboxItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : (
                    <Select
                      value={selectedDeptId}
                      onValueChange={(value) => {
                        setSelectedDeptId(value);
                        setSelectedDeptIds(value ? [value] : []);
                        const dept = visibilityOptions.departments.find((d) => d.id === value);
                        if (dept) setSelectedOrgId(dept.org_id);
                      }}
                      disabled
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder={t("Select department")} />
                      </SelectTrigger>
                      <SelectContent>
                        {visibilityOptions.departments.map((dept) => (
                          <SelectItem key={dept.id} value={dept.id}>
                            {dept.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              </>
            )}
          </div>
        </BaseModal.Content>
        <BaseModal.Footer
          submit={{
            label: t("Save"),
            disabled:
              updateVisibilityMutation.isPending ||
              (visibilityScope === "organization" && !selectedOrgId) ||
              (visibilityScope === "department" &&
                ((canMultiDept && selectedDeptIds.length === 0) ||
                  (!canMultiDept && !selectedDeptId))),
            onClick: async () => {
              if (!knowledgeBaseToEdit) return;
              const deptIds = canMultiDept
                ? selectedDeptIds
                : selectedDeptId
                  ? [selectedDeptId]
                  : [];
              const deptId = deptIds.length === 1 ? deptIds[0] : undefined;
              await updateVisibilityMutation.mutateAsync({
                visibility: selectedVisibility,
                org_id:
                  visibilityScope === "organization"
                    ? selectedOrgId
                    : visibilityScope === "department"
                      ? selectedOrgId
                      : undefined,
                dept_id:
                  visibilityScope === "department" ? deptId : undefined,
                public_dept_ids:
                  visibilityScope === "department" ? deptIds : undefined,
              });
            },
          }}
        >
          <></>
        </BaseModal.Footer>
      </BaseModal>

      {uploadModal}
    </div>
  );
};

export default KnowledgeBasesTab;