import {
  Search,
  Plus,
  Plug,
  Unplug,
  AlertCircle,
  Pencil,
  Trash2,
  Zap,
  X,
  Loader2,
  Eye,
  EyeOff,
  Cable,
  Database,
  CheckCircle2,
  XCircle,
  Cloud,
  Mail,
  ChevronDown,
} from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import OutlookConnectorForm from "./components/OutlookConnectorForm";
import SharePointCapabilityBanner from "./components/SharePointCapabilityBanner";
import { ENABLE_OUTLOOK_CONNECTOR } from "@/customization/feature-flags";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import Loading from "@/components/ui/loading";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useNameAvailability } from "@/controllers/API/queries/common/use-name-availability";
import {
  useGetConnectorCatalogue,
  type ConnectorInfo,
} from "@/controllers/API/queries/connectors/use-get-connector-catalogue";
import {
  useCreateConnector,
  useUpdateConnector,
  useDeleteConnector,
  useTestConnectorConnection,
  useTestConnectorDraftConnection,
  useDisconnectConnector,
} from "@/controllers/API/queries/connectors/use-mutate-connector";
import useAlertStore from "@/stores/alertStore";

type ProviderFilter =
  | "all"
  | "postgresql"
  | "oracle"
  | "sqlserver"
  | "mysql"
  | "azure_blob"
  | "sharepoint"
  | "outlook";

const PROVIDER_LABELS: Record<string, string> = {
  postgresql: "PostgreSQL",
  oracle: "Oracle",
  sqlserver: "SQL Server",
  mysql: "MySQL",
  azure_blob: "Azure Blob Storage",
  sharepoint: "SharePoint",
  outlook: "Microsoft Outlook",
};

const PROVIDER_PORTS: Record<string, number> = {
  postgresql: 5432,
  oracle: 1521,
  sqlserver: 1433,
  mysql: 3306,
};

const DB_PROVIDERS = new Set(["postgresql", "oracle", "sqlserver", "mysql"]);
const STORAGE_PROVIDERS = new Set(["azure_blob", "sharepoint"]);
const EMAIL_PROVIDERS = new Set(["outlook"]);
const DEFAULT_CONNECTOR_HOST =
  process.env.DEFAULT_CONNECTOR_HOST ||
  process.env.HOST_IP ||
  window.location.hostname;

function isDbProvider(provider: string): boolean {
  return DB_PROVIDERS.has(provider);
}

const BLANK_FORM = {
  name: "",
  description: "",
  provider: "postgresql",
  // DB fields
  host: DEFAULT_CONNECTOR_HOST,
  port: 5432,
  database_name: "",
  schema_name: "public",
  username: "",
  password: "",
  ssl_enabled: false,
  // Azure Blob fields
  azure_account_url: "",
  azure_container_name: "",
  azure_blob_prefix: "",
  // SharePoint fields
  sharepoint_site_url: "",
  sharepoint_library: "Shared Documents",
  sharepoint_folder: "",
  sharepoint_client_id: "",
  sharepoint_client_secret: "",
  sharepoint_tenant_id: "",
  // Outlook fields
  outlook_tenant_id: "",
  outlook_client_id: "",
  outlook_client_secret: "",
  visibility: "private",
  public_scope: "department",
  org_id: "",
  dept_id: "",
  public_dept_ids: [] as string[],
};

type FormState = typeof BLANK_FORM;

export default function ConnectorsCatalogueView(): JSX.Element {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<ProviderFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [editingConnector, setEditingConnector] = useState<ConnectorInfo | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [testPayloadKey, setTestPayloadKey] = useState<string | null>(null);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const [searchParams, setSearchParams] = useSearchParams();
  const { data: connectors, isLoading, error, refetch } = useGetConnectorCatalogue();
  const createMutation = useCreateConnector();
  const updateMutation = useUpdateConnector();
  const deleteMutation = useDeleteConnector();
  const testMutation = useTestConnectorConnection();
  const testDraftMutation = useTestConnectorDraftConnection();
  const disconnectMutation = useDisconnectConnector();

  const getErrorMessage = (err: any, fallback: string) =>
    err?.response?.data?.detail ||
    err?.response?.data?.message ||
    err?.message ||
    fallback;

  // Handle OAuth redirect results on mount. Always clear the mail-linking
  // loader on mount/return-from-OAuth so an in-flight spinner from before the
  // OAuth bounce can't get stuck on if the provider redirected back with an
  // error.
  useEffect(() => {
    setLinkingMailboxId(null);

    const success = searchParams.get("success");
    const errorParam = searchParams.get("error");

    if (success === "outlook_account_linked") {
      const email = searchParams.get("email") || "";
      const message = email
        ? t("Outlook mailbox linked successfully: {{email}}", { email })
        : t("Outlook mailbox linked successfully");
      setTestResult({ success: true, message });
      setSuccessData({ title: message });
      void refetch();
    } else if (errorParam) {
      const detail = searchParams.get("detail") || errorParam;
      const message = t("Outlook OAuth failed: {{detail}}", { detail });
      setTestResult({ success: false, message });
      setErrorData({ title: t("Mailbox linking failed"), list: [detail] });
    }

    if (success || errorParam) {
      // Clean OAuth params from URL without triggering navigation
      searchParams.delete("success");
      searchParams.delete("error");
      searchParams.delete("detail");
      searchParams.delete("email");
      setSearchParams(searchParams, { replace: true });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Browser back-button from OAuth can restore the page from bfcache with
  // React state intact — useEffect above does NOT re-run on bfcache restore.
  // pageshow fires in both cases (e.persisted=true means restored from cache),
  // so we clear the loader here too.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) setLinkingMailboxId(null);
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  const { role, permissions, userData } = useContext(AuthContext);
  const canViewConnectorPage = permissions?.includes("view_connector_page");
  const canAddConnector = permissions?.includes("add_connector");
  const canMultiDept = role === "super_admin" || role === "root";
  const canSeeVisibilityColumn = true;
  const isDepartmentAdmin = role === "department_admin";
  const isSuperAdmin = role === "super_admin";
  const userDeptId = userData?.department_id ?? null;
  const userId = userData?.id ?? null;

  const getConnectorDeptIds = (connector: ConnectorInfo) => {
    const ids = new Set<string>();
    (connector.public_dept_ids || []).forEach((id) => ids.add(id));
    if (connector.dept_id) ids.add(connector.dept_id);
    return Array.from(ids);
  };

  const isMultiDeptConnector = (connector: ConnectorInfo) =>
    connector.visibility === "public" &&
    connector.public_scope === "department" &&
    getConnectorDeptIds(connector).length > 1;

  const isDeptScopedForUser = (connector: ConnectorInfo) =>
    Boolean(userDeptId && getConnectorDeptIds(connector).includes(userDeptId));

  const canEditConnector = (connector: ConnectorInfo) => {
    if (role === "root") {
      return (
        connector.created_by_id === userId &&
        !connector.org_id &&
        !connector.dept_id
      );
    }
    if (role === "super_admin") return true;
    if (role === "department_admin") {
      if (isMultiDeptConnector(connector)) return false;
      if (connector.visibility === "public" && connector.public_scope === "organization") return false;
      if (connector.visibility === "public" && connector.public_scope === "department") {
        return isDeptScopedForUser(connector);
      }
      if (connector.visibility === "private") return isDeptScopedForUser(connector);
      return false;
    }
    if (role === "developer" || role === "business_user") {
      return connector.visibility === "private" && connector.created_by_id === userId;
    }
    return false;
  };

  const canDeleteConnector = (connector: ConnectorInfo) => {
    if (role === "root") {
      return (
        connector.created_by_id === userId &&
        !connector.org_id &&
        !connector.dept_id
      );
    }
    if (role === "super_admin") return true;
    if (role === "department_admin") {
      if (isMultiDeptConnector(connector)) return false;
      if (connector.visibility === "public" && connector.public_scope === "organization") return false;
      if (connector.visibility === "public" && connector.public_scope === "department") {
        return isDeptScopedForUser(connector);
      }
      if (connector.visibility === "private") return isDeptScopedForUser(connector);
      return false;
    }
    if (role === "developer" || role === "business_user") {
      return connector.visibility === "private" && connector.created_by_id === userId;
    }
    return false;
  };

  const [visibilityOptions, setVisibilityOptions] = useState<{
    organizations: { id: string; name: string }[];
    departments: { id: string; name: string; org_id: string }[];
  }>({ organizations: [], departments: [] });
  const userDeptOrgId = useMemo(() => {
    if (!userDeptId) return null;
    return (
      visibilityOptions.departments.find((dept) => dept.id === userDeptId)
        ?.org_id ?? null
    );
  }, [userDeptId, visibilityOptions.departments]);

  const [form, setForm] = useState<FormState>({ ...BLANK_FORM });

  useEffect(() => {
    if (!canViewConnectorPage) return;
    api.get(`${getURL("CONNECTOR_CATALOGUE")}/visibility-options`).then((res) => {
      setVisibilityOptions(res.data || { organizations: [], departments: [] });
      const firstOrg = res.data?.organizations?.[0]?.id || "";
      const firstDept = res.data?.departments?.[0]?.id || "";
      setForm((prev) => ({ ...prev, org_id: prev.org_id || firstOrg, dept_id: prev.dept_id || firstDept }));
    });
  }, [canViewConnectorPage]);

  const departmentsForSelectedOrg = useMemo(
    () =>
      visibilityOptions.departments.filter(
        (d) => !form.org_id || d.org_id === form.org_id,
      ),
    [visibilityOptions.departments, form.org_id],
  );
  const visibilityScope = useMemo<"private" | "department" | "organization">(() => {
    if (form.visibility === "private") return "private";
    return form.public_scope === "organization" ? "organization" : "department";
  }, [form.visibility, form.public_scope]);
  const selectedDeptLabel = useMemo(() => {
    const selectedIds = canMultiDept ? form.public_dept_ids : form.dept_id ? [form.dept_id] : [];
    if (selectedIds.length === 0) return t("Select departments");
    const names = departmentsForSelectedOrg
      .filter((dept) => selectedIds.includes(dept.id))
      .map((dept) => dept.name);
    if (names.length === 0) return t("Select departments");
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [canMultiDept, departmentsForSelectedOrg, form.dept_id, form.public_dept_ids, t]);
  const getVisibilityBadgeClass = (c: ConnectorInfo) => {
    if (c.visibility === "private") {
      return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200";
    }
    if (c.public_scope === "organization") {
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
    }
    return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
  };
  const getDepartmentScopeLabel = (connector: ConnectorInfo) => {
    const deptNameById = new Map(
      visibilityOptions.departments.map((dept) => [dept.id, dept.name]),
    );
    if (connector.visibility === "public" && connector.public_scope === "organization") {
      return t("All departments");
    }
    const deptIds =
      connector.visibility === "public" && connector.public_scope === "department"
        ? connector.public_dept_ids?.length
          ? connector.public_dept_ids
          : connector.dept_id
            ? [connector.dept_id]
            : []
        : connector.dept_id
          ? [connector.dept_id]
          : [];
    if (deptIds.length === 0) return "-";
    const names = deptIds.map((id) => deptNameById.get(id) || id);
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  };
  const setVisibilityScope = (scope: "private" | "department" | "organization") => {
    setForm((prev) => ({
      ...prev,
      visibility: scope === "private" ? "private" : "public",
      public_scope: scope === "private" ? "department" : scope,
      org_id:
        scope === "private"
          ? prev.org_id
          : scope === "organization"
            ? prev.org_id
            : prev.org_id,
      dept_id: scope === "department" ? prev.dept_id : "",
      public_dept_ids: scope === "department" ? prev.public_dept_ids : [],
    }));
  };
  const effectiveNameScope = useMemo(() => {
    let orgId: string | null = form.org_id || null;
    let deptId: string | null = form.dept_id || null;
    const canMultiDept = role === "super_admin" || role === "root";

    if (form.visibility === "public") {
      if (form.public_scope === "organization") {
        orgId =
          orgId ||
          ((role === "developer" || role === "department_admin")
            ? visibilityOptions.organizations[0]?.id || null
            : null);
        deptId = null;
      } else if (form.public_scope === "department") {
        if (canMultiDept) {
          if (form.public_dept_ids.length === 1) {
            deptId = form.public_dept_ids[0];
          } else {
            deptId = null;
          }
        } else {
          deptId = deptId || userDeptId || visibilityOptions.departments[0]?.id || null;
        }
        if (!orgId) {
          const selectedDept =
            visibilityOptions.departments.find((d) => d.id === deptId) ||
            visibilityOptions.departments[0];
          orgId = selectedDept?.org_id || null;
        }
      }
    } else if (role === "developer" || role === "department_admin") {
      const defaultDept =
        visibilityOptions.departments.find((d) => d.id === userDeptId) ||
        visibilityOptions.departments[0];
      if (defaultDept) {
        orgId = orgId || defaultDept.org_id;
        deptId = deptId || defaultDept.id;
      }
    }

    return { org_id: orgId, dept_id: deptId };
  }, [
    form.visibility,
    form.public_scope,
    form.public_dept_ids,
    form.org_id,
    form.dept_id,
    role,
    visibilityOptions.departments,
    visibilityOptions.organizations,
    userDeptId,
  ]);
  const connectorNameAvailability = useNameAvailability({
    entity: "connector",
    name: form.name,
    org_id: effectiveNameScope.org_id,
    dept_id: effectiveNameScope.dept_id,
    exclude_id: editingConnector?.id ?? null,
    enabled: showModal && form.name.trim().length > 0,
  });

  useEffect(() => {
    if (form.visibility !== "public") return;
    const isOrgLockedRole =
      role === "developer" || role === "department_admin" || role === "business_user";
    if (
      form.public_scope === "organization" &&
      isOrgLockedRole &&
      !form.org_id
    ) {
      const fallbackOrgId =
        userDeptOrgId || visibilityOptions.organizations[0]?.id;
      if (fallbackOrgId) {
        setForm((prev) => ({ ...prev, org_id: fallbackOrgId }));
      }
      return;
    }
    const canMultiDept = role === "super_admin" || role === "root";
    if (form.public_scope === "department" && !canMultiDept && !form.dept_id) {
      const firstDept =
        visibilityOptions.departments.find((d) => d.id === userDeptId) ||
        visibilityOptions.departments[0];
      if (firstDept) {
        setForm((prev) => ({
          ...prev,
          dept_id: firstDept.id,
          org_id: prev.org_id || firstDept.org_id,
        }));
      }
    }
    if (form.public_scope === "department" && canMultiDept) {
      const firstDept = departmentsForSelectedOrg[0] || visibilityOptions.departments[0];
      if (!firstDept) return;
      const hasSelectedDept = form.public_dept_ids.some((id) =>
        departmentsForSelectedOrg.some((dept) => dept.id === id),
      );
      if (!form.org_id || !hasSelectedDept) {
        setForm((prev) => ({
          ...prev,
          org_id: prev.org_id || firstDept.org_id,
          dept_id: prev.dept_id || firstDept.id,
          public_dept_ids: hasSelectedDept ? prev.public_dept_ids : [firstDept.id],
        }));
      }
    }
  }, [
    form.visibility,
    form.public_scope,
    form.org_id,
    form.dept_id,
    form.public_dept_ids,
    departmentsForSelectedOrg,
    role,
    visibilityOptions.organizations,
    visibilityOptions.departments,
    userDeptId,
    userDeptOrgId,
  ]);

  const resetForm = () => {
    setForm({ ...BLANK_FORM });
    setTestResult(null);
    setTestPayloadKey(null);
    setShowPassword(false);
  };

  const openAddModal = () => {
    resetForm();
    setEditingConnector(null);
    setShowModal(true);
  };

  const openEditModal = (connector: ConnectorInfo) => {
    const cfg = connector.provider_config ?? {};
    setForm({
      name: connector.name,
      description: connector.description || "",
      provider: connector.provider,
      // DB fields
      host: connector.host ?? DEFAULT_CONNECTOR_HOST,
      port: connector.port ?? PROVIDER_PORTS[connector.provider] ?? 5432,
      database_name: connector.database_name ?? "",
      schema_name: connector.schema_name ?? "public",
      username: connector.username ?? "",
      password: "",
      ssl_enabled: connector.ssl_enabled,
      // Azure Blob (managed identity via account URL)
      azure_account_url: cfg.account_url ?? "",
      azure_container_name: cfg.container_name ?? "",
      azure_blob_prefix: cfg.blob_prefix ?? "",
      // SharePoint (client_secret is masked; user must re-enter to update)
      sharepoint_site_url: cfg.site_url ?? "",
      sharepoint_library: cfg.library ?? "Shared Documents",
      sharepoint_folder: cfg.folder ?? "",
      sharepoint_client_id: cfg.client_id ?? "",
      sharepoint_client_secret: "",
      sharepoint_tenant_id: cfg.tenant_id ?? "",
      // Outlook (client_secret is masked; user must re-enter to update)
      outlook_tenant_id: cfg.tenant_id ?? "",
      outlook_client_id: cfg.client_id ?? "",
      outlook_client_secret: "",
      visibility: connector.visibility ?? "private",
      public_scope: connector.public_scope ?? "department",
      org_id: connector.org_id ?? "",
      dept_id: connector.dept_id ?? "",
      public_dept_ids: connector.public_dept_ids || [],
    });
    setEditingConnector(connector);
    setTestResult(null);
    setShowModal(true);
  };

  const handleProviderChange = (provider: string) => {
    setForm((prev) => ({
      ...prev,
      provider,
      port: PROVIDER_PORTS[provider] ?? prev.port,
      schema_name:
        provider === "postgresql"
          ? "public"
          : provider === "oracle"
          ? ""
          : provider === "sqlserver"
          ? "dbo"
          : prev.schema_name,
    }));
  };

  const buildPayload = () => {
    const scopePayload = {
      visibility: form.visibility as "private" | "public",
      public_scope: form.visibility === "public" ? form.public_scope : null,
      org_id:
        form.org_id ||
        ((role === "developer" || role === "department_admin" || role === "business_user") &&
        form.visibility === "public" &&
        form.public_scope === "organization"
          ? userDeptOrgId || visibilityOptions.organizations[0]?.id
          : undefined),
      dept_id:
        form.dept_id ||
        ((form.visibility === "public" &&
          form.public_scope === "department" &&
          role !== "super_admin" &&
          role !== "root")
          ? userDeptId || visibilityOptions.departments[0]?.id
          : undefined),
      public_dept_ids:
        form.visibility === "public" && form.public_scope === "department"
          ? form.public_dept_ids
          : [],
    };

    if (form.provider === "outlook") {
      const provider_config: Record<string, string> = {
        tenant_id: form.outlook_tenant_id,
        client_id: form.outlook_client_id,
      };
      if (form.outlook_client_secret) {
        provider_config.client_secret = form.outlook_client_secret;
      }
      return {
        name: form.name,
        description: form.description || undefined,
        provider: "outlook",
        provider_config,
        ...scopePayload,
      };
    }

    if (form.provider === "azure_blob") {
      const provider_config: Record<string, string> = {
        account_url: form.azure_account_url,
        container_name: form.azure_container_name,
      };
      if (form.azure_blob_prefix) {
        provider_config.blob_prefix = form.azure_blob_prefix;
      }
      return {
        name: form.name,
        description: form.description || undefined,
        provider: form.provider,
        provider_config,
        ...scopePayload,
      };
    }

    if (form.provider === "sharepoint") {
      const provider_config: Record<string, string> = {
        site_url: form.sharepoint_site_url,
        library: form.sharepoint_library,
        client_id: form.sharepoint_client_id,
      };
      if (form.sharepoint_tenant_id) {
        provider_config.tenant_id = form.sharepoint_tenant_id;
      }
      if (form.sharepoint_client_secret) {
        provider_config.client_secret = form.sharepoint_client_secret;
      }
      if (form.sharepoint_folder) {
        provider_config.folder = form.sharepoint_folder;
      }
      return {
        name: form.name,
        description: form.description || undefined,
        provider: form.provider,
        provider_config,
        ...scopePayload,
      };
    }

    // DB provider
    const payload: any = {
      name: form.name,
      description: form.description || undefined,
      provider: form.provider,
      host: form.host,
      port: form.port,
      database_name: form.database_name,
      schema_name: form.schema_name,
      username: form.username,
      ssl_enabled: form.ssl_enabled,
    };
    if (form.password) payload.password = form.password;
    return { ...payload, ...scopePayload };
  };

  const isSaveDisabled = () => {
    if (!form.name) return true;
    if (form.visibility === "public") {
      if (!form.public_scope) return true;
      if (form.public_scope === "organization") {
        const effectiveOrgId =
          form.org_id ||
          ((role === "developer" || role === "department_admin" || role === "business_user")
            ? userDeptOrgId || visibilityOptions.organizations[0]?.id
            : "");
        if (!effectiveOrgId) return true;
      }
      if (form.public_scope === "department") {
        const canMultiDept = role === "super_admin" || role === "root";
        if (canMultiDept && form.public_dept_ids.length === 0) return true;
        const effectiveDeptId =
          form.dept_id ||
          (!canMultiDept ? userDeptId || visibilityOptions.departments[0]?.id : "");
        if (!canMultiDept && !effectiveDeptId) return true;
      }
    }
    if (form.provider === "azure_blob") {
      // Azure Blob managed identity requires account_url + container_name
      if (!form.azure_container_name) return true;
      if (!form.azure_account_url) return true;
    } else if (form.provider === "sharepoint") {
      if (!form.sharepoint_site_url || !form.sharepoint_client_id) return true;
      if (!editingConnector && !form.sharepoint_client_secret) return true;
    } else if (form.provider === "outlook") {
      if (!form.outlook_tenant_id || !form.outlook_client_id) return true;
      if (!editingConnector && !form.outlook_client_secret) return true;
    } else {
      // DB provider
      if (!form.host || !form.database_name || !form.username) return true;
      if (!editingConnector && !form.password) return true;
    }
    if (connectorNameAvailability.isFetching) return true;
    if (connectorNameAvailability.isNameTaken) return true;
    return createMutation.isPending || updateMutation.isPending;
  };

  const handleSave = async () => {
    if (connectorNameAvailability.isNameTaken) {
      setErrorData({
        title: t("Name already in use"),
        list: [t("Choose a different connector name for this scope.")],
      });
      return;
    }
    try {
      const payload = buildPayload();
      if (!editingConnector && form.provider !== "outlook") {
        const currentTestKey = JSON.stringify(payload);
        let result = testResult && testPayloadKey === currentTestKey ? testResult : null;
        let autoTestRan = false;
        if (!result) {
          result = await testDraftMutation.mutateAsync(payload);
          setTestResult(result);
          setTestPayloadKey(currentTestKey);
          autoTestRan = true;
        }
        if (!result) {
          setErrorData({ title: t("Connection failed"), list: [t("Connection test did not return a result.")] });
          return;
        }
        if (!result.success) {
          setErrorData({ title: t("Connection failed"), list: [result.message] });
          return;
        }
        if (autoTestRan) {
          setSuccessData({ title: result.message || t("Connection verified.") });
        }
      }
      if (editingConnector) {
        await updateMutation.mutateAsync({ id: editingConnector.id, payload });
        setSuccessData({ title: t('Connector "{{name}}" updated.', { name: payload.name }) });
      } else {
        await createMutation.mutateAsync(payload as any);
        setSuccessData({ title: t('Connector "{{name}}" created.', { name: payload.name }) });
      }
      await refetch();
      setShowModal(false);
      resetForm();
    } catch (err: any) {
      setErrorData({
        title: editingConnector ? t("Failed to update connector") : t("Failed to create connector"),
        list: [getErrorMessage(err, t("Save request failed"))],
      });
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const connectorName =
        connectors?.find((connector) => connector.id === id)?.name || t("Connector");
      await deleteMutation.mutateAsync(id);
      await refetch();
      setDeleteConfirm(null);
      setSuccessData({ title: t("{{name}} deleted.", { name: connectorName }) });
    } catch (err: any) {
      setErrorData({
        title: t("Failed to delete connector"),
        list: [getErrorMessage(err, t("Delete request failed"))],
      });
    }
  };

  const handleTestConnection = async (connectorId: string) => {
    setActioningConnectorId(connectorId);
    try {
      const result = await testMutation.mutateAsync(connectorId);
      setTestResult(result);
      await refetch();
      if (result.success) {
        setSuccessData({ title: result.message || t("Connection verified.") });
      } else {
        setErrorData({ title: t("Connection failed"), list: [result.message] });
      }
    } catch (err: any) {
      const detail = getErrorMessage(err, t("Test request failed"));
      setTestResult({ success: false, message: detail });
      setErrorData({ title: t("Connection test failed"), list: [detail] });
    } finally {
      setActioningConnectorId(null);
    }
  };

  const handleModalTestConnection = async () => {
    try {
      let payload: any;
      if (editingConnector) {
        payload = buildPayload();
        const result = await testMutation.mutateAsync({
          id: editingConnector.id,
          payload,
        });
        setTestResult(result);
        return;
      }

      if (form.provider === "azure_blob") {
        payload = {
          provider: form.provider,
          provider_config: {
            account_url: form.azure_account_url,
            container_name: form.azure_container_name,
            ...(form.azure_blob_prefix ? { blob_prefix: form.azure_blob_prefix } : {}),
          },
        };
      } else if (form.provider === "sharepoint") {
        payload = {
          provider: form.provider,
          provider_config: {
            site_url: form.sharepoint_site_url,
            library: form.sharepoint_library,
            client_id: form.sharepoint_client_id,
            client_secret: form.sharepoint_client_secret,
            ...(form.sharepoint_tenant_id ? { tenant_id: form.sharepoint_tenant_id } : {}),
            ...(form.sharepoint_folder ? { folder: form.sharepoint_folder } : {}),
          },
        };
      } else if (form.provider === "outlook") {
        payload = {
          provider: form.provider,
          provider_config: {
            tenant_id: form.outlook_tenant_id,
            client_id: form.outlook_client_id,
            client_secret: form.outlook_client_secret,
          },
        };
      } else {
        payload = {
          provider: form.provider,
          host: form.host,
          port: form.port,
          database_name: form.database_name,
          schema_name: form.schema_name,
          username: form.username,
          password: form.password,
          ssl_enabled: form.ssl_enabled,
        };
      }

      const result = await testDraftMutation.mutateAsync(payload);
      setTestResult(result);
      setTestPayloadKey(JSON.stringify(payload));
      if (result.success) {
        setSuccessData({ title: result.message || t("Connection verified.") });
      } else {
        setErrorData({ title: t("Connection failed"), list: [result.message] });
      }
    } catch (err: any) {
      const detail = getErrorMessage(err, t("Test request failed"));
      setTestResult({ success: false, message: detail });
      setTestPayloadKey(null);
      setErrorData({ title: t("Connection test failed"), list: [detail] });
    }
  };

  const handleToggleConnection = async (connector: ConnectorInfo) => {
    setActioningConnectorId(connector.id);
    try {
      if (connector.status === "connected") {
        await disconnectMutation.mutateAsync(connector.id);
        setSuccessData({ title: t('Connector "{{name}}" disconnected.', { name: connector.name }) });
      } else {
        const result = await testMutation.mutateAsync(connector.id);
        if (result.success) {
          setSuccessData({
            title: result.message || t('Connector "{{name}}" connected.', { name: connector.name }),
          });
        } else {
          setErrorData({ title: t("Connection failed"), list: [result.message] });
        }
      }
      await refetch();
    } catch (err: any) {
      setErrorData({
        title: t("Connector action failed"),
        list: [getErrorMessage(err, t("Unable to update connector status"))],
      });
    } finally {
      setActioningConnectorId(null);
    }
  };

  const [actioningConnectorId, setActioningConnectorId] = useState<string | null>(null);
  const [linkingMailboxId, setLinkingMailboxId] = useState<string | null>(null);

  const tableScrollRef = useRef<HTMLDivElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const phantomRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);

  useEffect(() => {
    const scroll = tableScrollRef.current;
    const mirror = mirrorRef.current;
    const phantom = phantomRef.current;
    if (!scroll || !mirror || !phantom) return;
    const syncWidth = () => { phantom.style.width = `${scroll.scrollWidth}px`; };
    syncWidth();
    const ro = new ResizeObserver(syncWidth);
    ro.observe(scroll);
    // Also watch inner content so phantom re-syncs when the table widens
    // after async data loads (ResizeObserver only fires on observed-element
    // size changes, not on scrollWidth growth of its children).
    const inner = scroll.firstElementChild as Element | null;
    if (inner) ro.observe(inner);
    const raf = requestAnimationFrame(syncWidth);
    const onScrollContent = () => {
      if (syncingRef.current) return;
      syncingRef.current = true;
      mirror.scrollLeft = scroll.scrollLeft;
      syncingRef.current = false;
    };
    const onScrollMirror = () => {
      if (syncingRef.current) return;
      syncingRef.current = true;
      scroll.scrollLeft = mirror.scrollLeft;
      syncingRef.current = false;
    };
    scroll.addEventListener("scroll", onScrollContent, { passive: true });
    mirror.addEventListener("scroll", onScrollMirror, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      scroll.removeEventListener("scroll", onScrollContent);
      mirror.removeEventListener("scroll", onScrollMirror);
    };
  }, []);
  const handleLinkMailbox = async (connectorId: string) => {
    try {
      setLinkingMailboxId(connectorId);
      const res = await api.get(`/api/outlook/${connectorId}/oauth/start`);
      const { authorize_url } = res.data;
      if (authorize_url) {
        window.location.href = authorize_url;
        return;
      }
      throw new Error(t("OAuth authorization URL was not returned."));
    } catch (err: any) {
      const detail = getErrorMessage(err, t("Failed to start OAuth flow"));
      setTestResult({ success: false, message: detail });
      setErrorData({ title: t("Mailbox linking failed"), list: [detail] });
      setLinkingMailboxId(null);
    }
  };

  /* ---- Filtering ---- */
  const displayConnectors = connectors ?? [];
  const filteredConnectors = displayConnectors.filter((c) => {
    const matchesFilter = filter === "all" || c.provider === filter;
    const matchesSearch =
      !searchQuery ||
      c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.provider.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.database_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.provider_config?.container_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.provider_config?.site_url?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.provider_config?.client_id?.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  /* ---- Helpers ---- */
  const getStatusIcon = (status: string) => {
    switch (status) {
      case "connected":
        return <Plug className="h-4 w-4 text-green-500" />;
      case "error":
        return <AlertCircle className="h-4 w-4 text-red-500" />;
      default:
        return <Unplug className="h-4 w-4 text-gray-400" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      connected: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
      disconnected: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
      error: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    };
    return styles[status] || styles.disconnected;
  };

  const getProviderBadge = (provider: string) => {
    const styles: Record<string, string> = {
      postgresql: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
      oracle: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
      sqlserver: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
      mysql: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
      azure_blob: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400",
      sharepoint: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
      outlook: "bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400",
    };
    return styles[provider] || "bg-gray-100 text-gray-700";
  };

  const getConnectorTarget = (c: ConnectorInfo): string => {
    if (c.provider === "azure_blob") {
      return c.provider_config?.container_name ?? "—";
    }
    if (c.provider === "sharepoint") {
      return c.provider_config?.site_url ?? "—";
    }
    if (c.provider === "outlook") {
      return c.provider_config?.client_id ?? "—";
    }
    return c.host ? `${c.host}:${c.port}` : "—";
  };

  const getConnectorDb = (c: ConnectorInfo): string => {
    if (STORAGE_PROVIDERS.has(c.provider) || EMAIL_PROVIDERS.has(c.provider)) return "—";
    return c.database_name ?? "—";
  };

  const getConnectorSchema = (c: ConnectorInfo): string => {
    if (STORAGE_PROVIDERS.has(c.provider) || EMAIL_PROVIDERS.has(c.provider)) return "—";
    return c.schema_name ?? "—";
  };

  const getConnectorVisibilityLabel = (c: ConnectorInfo): string => {
    if (c.visibility === "private") return t("Private");
    if (c.public_scope === "organization") {
      return t("Organization");
    }
    if (c.public_scope === "department") {
      return t("Department");
    }
    return t("Private");
  };

  const FILTER_TABS: ProviderFilter[] = ["all", "postgresql", "oracle", "sqlserver", "mysql", "azure_blob", "sharepoint", ...(ENABLE_OUTLOOK_CONNECTOR ? ["outlook" as const] : [])];

  /* ---- JSX ---- */
  if (!canViewConnectorPage) {
    return (
      <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
        {t("You do not have permission to access the Connectors page.")}
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex flex-shrink-0 flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <h1 className="text-lg font-semibold md:text-xl">{t("Connectors")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Configure data source connections for agents")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search connectors...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring sm:w-64"
            />
          </div>
          {canAddConnector && (
            <button
              onClick={openAddModal}
              className="inline-flex items-center gap-2 rounded-lg  px-4 py-2.5 text-sm font-medium !bg-[var(--button-primary)] hover:!bg-[var(--button-primary-hover)] disabled:!bg-[var(--button-primary-disabled)] text-primary-foreground"
            >
              <Plus className="h-4 w-4" />
              {t("Add Connector")}
            </button>
          )}
        </div>
      </div>

      {/* Provider filter tabs */}
      <div className="flex flex-wrap gap-2 border-b px-4 py-3 sm:px-6 md:px-8">
        {FILTER_TABS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-4 py-1.5 text-xs font-medium transition-colors ${
              filter === f
                ? "!bg-[var(--button-primary)] hover:!bg-[var(--button-primary-hover)] disabled:!bg-[var(--button-primary-disabled)] text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            {f === "all" ? t("All") : t(PROVIDER_LABELS[f] || f)}
          </button>
        ))}
      </div>

      {/* Table */}
      <style>{`
        .conn-table-scroll::-webkit-scrollbar { height: 0; }
        .conn-table-scroll { scrollbar-width: none; }
        .conn-mirror-bar::-webkit-scrollbar { height: 8px; }
        .conn-mirror-bar::-webkit-scrollbar-track { background: hsl(var(--muted)); border-radius: 9999px; }
        .conn-mirror-bar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground)); border-radius: 9999px; }
        .conn-mirror-bar::-webkit-scrollbar-thumb:hover { background: hsl(var(--foreground) / 0.8); }
        .conn-mirror-bar { scrollbar-width: thin; scrollbar-color: hsl(var(--muted-foreground)) hsl(var(--muted)); }
      `}</style>
      <div className="flex-1 flex flex-col overflow-hidden p-4 sm:p-6 gap-3">
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border bg-card">
          <div ref={tableScrollRef} className="conn-table-scroll flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        ) : (
          <>
            {!!error && (
              <div className="mx-4 mt-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {t("Failed to load connectors.")}
              </div>
            )}
              <table className="w-full min-w-[1200px]">
                <thead className="sticky top-0 z-10 bg-card shadow-sm">
                  <tr className="border-b border-border">
                    {[
                      t("Connector Name"),
                      t("Provider"),
                      ...(isDepartmentAdmin ? [t("Created By")] : []),
                      ...(isSuperAdmin ? [t("Department Scope")] : []),
                      t("Host / Container / Site"),
                      t("Database"),
                      t("Schema"),
                      ...(canSeeVisibilityColumn ? [t("Visibility")] : []),
                      t("Status"),
                      t("Tables"),
                      ...(canAddConnector ? [t("Actions")] : []),
                    ].map((h) => (
                      <th
                        key={h}
                        className={
                          h === "Connector Name"
                            ? "w-[260px] min-w-[260px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                            : h === "Host / Container / Site"
                              ? "w-[210px] min-w-[210px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                              : h === "Created By"
                                ? "w-[150px] min-w-[150px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                : h === "Department Scope"
                                  ? "w-[140px] min-w-[140px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                  : h === "Provider"
                                    ? "w-[140px] min-w-[140px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                    : h === "Database"
                                      ? "w-[96px] min-w-[96px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                      : h === "Schema"
                                        ? "w-[88px] min-w-[88px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                        : h === "Visibility"
                                          ? "w-[110px] min-w-[110px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                          : h === "Status"
                                            ? "w-[120px] min-w-[120px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                            : h === "Tables"
                                              ? "w-[70px] min-w-[70px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                              : h === "Actions"
                                                ? "w-[140px] min-w-[140px] px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                                                : "px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                        }
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {filteredConnectors.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7 + (isDepartmentAdmin ? 1 : 0) + (isSuperAdmin ? 1 : 0) + (canSeeVisibilityColumn ? 1 : 0) + (canAddConnector ? 1 : 0)}
                        className="px-4 py-12 text-center text-muted-foreground"
                      >
                        <div className="flex flex-col items-center gap-3">
                          <Cable className="h-10 w-10 text-muted-foreground/50" />
                          <p>{t("No connectors found")}</p>
                          {canAddConnector && (
                            <button
                              onClick={openAddModal}
                              className="text-primary hover:underline text-sm"
                            >
                              {t("Add your first connector")}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    filteredConnectors.map((c) => (
                      <tr key={c.id} className="group hover:bg-muted/50">
                        <td className="w-[260px] min-w-[260px] px-4 py-4">
                          <div
                            className="max-w-[240px] line-clamp-2 font-semibold leading-6"
                            title={c.name}
                          >
                            {c.name}
                          </div>
                          {c.description && (
                            <div
                              className="mt-1 max-w-[240px] line-clamp-1 text-xs text-muted-foreground"
                              title={c.description}
                            >
                              {c.description}
                            </div>
                          )}
                        </td>
                        <td className="w-[140px] min-w-[140px] px-4 py-4">
                          <span
                            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${getProviderBadge(c.provider)}`}
                          >
                            {STORAGE_PROVIDERS.has(c.provider) ? (
                              <Cloud className="h-3 w-3" />
                            ) : (
                              <Database className="h-3 w-3" />
                            )}
                            {t(PROVIDER_LABELS[c.provider] || c.provider)}
                          </span>
                        </td>
                        {isDepartmentAdmin && (
                          <td className="w-[150px] min-w-[150px] px-4 py-4 text-sm text-muted-foreground">
                            <div
                              className="max-w-[140px] truncate"
                              title={c.created_by_email || c.created_by || "-"}
                            >
                              {c.created_by || "-"}
                            </div>
                          </td>
                        )}
                        {isSuperAdmin && (
                          <td className="w-[140px] min-w-[140px] px-4 py-4">
                            <span
                              className="inline-block max-w-[140px] truncate text-sm text-muted-foreground"
                              title={getDepartmentScopeLabel(c)}
                            >
                              {getDepartmentScopeLabel(c)}
                            </span>
                          </td>
                        )}
                        <td className="w-[210px] min-w-[210px] px-4 py-4">
                          <span
                            className="inline-block max-w-[210px] truncate text-sm font-mono"
                            title={getConnectorTarget(c)}
                          >
                            {getConnectorTarget(c)}
                          </span>
                        </td>
                        <td className="w-[96px] min-w-[96px] px-4 py-4">
                          <span
                            className="inline-block max-w-[96px] truncate text-sm"
                            title={getConnectorDb(c)}
                          >
                            {getConnectorDb(c)}
                          </span>
                        </td>
                        <td className="w-[88px] min-w-[88px] px-4 py-4">
                          <span
                            className="inline-block max-w-[88px] truncate text-sm text-muted-foreground"
                            title={getConnectorSchema(c)}
                          >
                            {getConnectorSchema(c)}
                          </span>
                        </td>
                        {canSeeVisibilityColumn && (
                          <td className="w-[110px] min-w-[110px] px-4 py-4">
                            <span
                              className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${getVisibilityBadgeClass(c)}`}
                            >
                              {getConnectorVisibilityLabel(c)}
                            </span>
                          </td>
                        )}
                        <td className="w-[120px] min-w-[120px] px-4 py-4">
                          <div className="flex items-center gap-1.5">
                            {getStatusIcon(c.status)}
                            <span
                              className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${getStatusBadge(c.status)}`}
                            >
                              {c.status.charAt(0).toUpperCase() + c.status.slice(1)}
                            </span>
                          </div>
                        </td>
                        <td className="w-[70px] min-w-[70px] px-4 py-4">
                          <span className="text-sm font-medium">
                            {STORAGE_PROVIDERS.has(c.provider) || EMAIL_PROVIDERS.has(c.provider)
                              ? "-"
                              : (c.tables_metadata?.length ?? "-")}
                          </span>
                        </td>
                        {canAddConnector && (
                          <td className="w-[140px] min-w-[140px] px-4 py-4">
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => handleToggleConnection(c)}
                                disabled={actioningConnectorId === c.id}
                                className={`rounded p-1.5 transition-colors ${
                                  c.status === "connected"
                                    ? "text-green-500 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-900/20"
                                    : "text-muted-foreground hover:bg-green-50 hover:text-green-500 dark:hover:bg-green-900/20"
                                }`}
                                title={c.status === "connected" ? t("Disconnect") : t("Connect")}
                              >
                                {actioningConnectorId === c.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : c.status === "connected" ? (
                                  <Unplug className="h-4 w-4" />
                                ) : (
                                  <Plug className="h-4 w-4" />
                                )}
                              </button>
                              <button
                                onClick={() => handleTestConnection(c.id)}
                                disabled={actioningConnectorId === c.id}
                                className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                                title={t("Test Connection")}
                              >
                                {actioningConnectorId === c.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Zap className="h-4 w-4" />
                                )}
                              </button>
                              {EMAIL_PROVIDERS.has(c.provider) && (
                                <button
                                  onClick={() => handleLinkMailbox(c.id)}
                                  disabled={linkingMailboxId === c.id}
                                  className="rounded p-1.5 text-muted-foreground hover:bg-sky-50 hover:text-sky-600 dark:hover:bg-sky-900/20 transition-colors"
                                  title={t("Link Mailbox (OAuth)")}
                                >
                                  {linkingMailboxId === c.id ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Mail className="h-4 w-4" />
                                  )}
                                </button>
                              )}
                              {canEditConnector(c) && (
                                <button
                                  onClick={() => openEditModal(c)}
                                  className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                                  title={t("Edit")}
                                >
                                  <Pencil className="h-4 w-4" />
                                </button>
                              )}
                              {canDeleteConnector(c) && (
                                <button
                                  onClick={() => setDeleteConfirm(c.id)}
                                  className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
                                  title={t("Delete")}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
          </>
        )}
          </div>
          <div ref={mirrorRef} className="conn-mirror-bar flex-shrink-0 overflow-x-scroll overflow-y-hidden border-t" style={{ height: 12 }}>
            <div ref={phantomRef} style={{ height: 1 }} />
          </div>
        </div>
        <div className="text-center text-sm text-muted-foreground flex-shrink-0">
          {t("Showing {{shown}} of {{total}} connectors", {
            shown: filteredConnectors.length,
            total: displayConnectors.length,
          })}
        </div>
      </div>

      {/* Add/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-lg rounded-xl border bg-card p-6 shadow-xl">
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                {editingConnector ? t("Edit Connector") : t("Add Connector")}
              </h2>
              <button
                onClick={() => {
                  setShowModal(false);
                  resetForm();
                }}
                className="rounded p-1 hover:bg-muted"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
              {/* Name */}
              <div>
                <label className="mb-1.5 block text-sm font-medium">{t("Name")}</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder={t("e.g., Manufacturing DB")}
                />
                {form.name.trim().length > 0 &&
                  !connectorNameAvailability.isFetching &&
                  connectorNameAvailability.isNameTaken && (
                    <p className="mt-1 text-xs font-medium text-red-500">
                      {connectorNameAvailability.reason ??
                        t("This name is already taken in the selected scope.")}
                    </p>
                  )}
              </div>

              {/* Description */}
              <div>
                <label className="mb-1.5 block text-sm font-medium">{t("Description")}</label>
                <input
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder={t("Optional description")}
                />
              </div>

              <div className="rounded-lg border border-border p-4">
                <div className="mb-4">
                  <label className="mb-1.5 block text-sm font-medium">{t("Tenancy")}</label>
                  <p className="text-xs text-muted-foreground">
                    {t("Connectors use direct tenancy only. No approval flow applies here.")}
                  </p>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium">{t("Visibility Scope")}</label>
                    <select
                      value={visibilityScope}
                      onChange={(e) =>
                        setVisibilityScope(e.target.value as "private" | "department" | "organization")
                      }
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      <option value="private">{t("Private")}</option>
                      <option value="department">{t("Department")}</option>
                      <option value="organization">{t("Organization")}</option>
                    </select>
                  </div>

                  {visibilityScope === "organization" && (
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Organization")}</label>
                      <select
                        value={form.org_id}
                        onChange={(e) => setForm({ ...form, org_id: e.target.value })}
                        disabled={role === "developer" || role === "department_admin"}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-80"
                      >
                        <option value="">{t("Select organization")}</option>
                        {visibilityOptions.organizations.map((org) => (
                          <option key={org.id} value={org.id}>
                            {org.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {visibilityScope === "department" && (
                    <>
                      {canMultiDept && (
                        <div>
                          <label className="mb-1.5 block text-sm font-medium">{t("Organization")}</label>
                          <select
                            value={form.org_id}
                            onChange={(e) =>
                              setForm({ ...form, org_id: e.target.value, public_dept_ids: [] })
                            }
                            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                          >
                            <option value="">{t("Select organization")}</option>
                            {visibilityOptions.organizations.map((org) => (
                              <option key={org.id} value={org.id}>
                                {org.name}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}

                      <div>
                        <label className="mb-1.5 block text-sm font-medium">
                          {canMultiDept ? t("Departments") : t("Department")}
                        </label>
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
                                  checked={form.public_dept_ids.includes(dept.id)}
                                  onSelect={(event) => event.preventDefault()}
                                  onCheckedChange={(checked) => {
                                    setForm((prev) => ({
                                      ...prev,
                                      public_dept_ids: checked
                                        ? Array.from(new Set([...prev.public_dept_ids, dept.id]))
                                        : prev.public_dept_ids.filter((id) => id !== dept.id),
                                    }));
                                  }}
                                >
                                  {dept.name}
                                </DropdownMenuCheckboxItem>
                              ))}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : (
                          <select
                            value={form.dept_id}
                            disabled
                            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm opacity-80"
                          >
                            <option value="">{t("Select department")}</option>
                            {visibilityOptions.departments.map((dept) => (
                              <option key={dept.id} value={dept.id}>
                                {dept.name}
                              </option>
                            ))}
                          </select>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Provider */}
              <div>
                <label className="mb-1.5 block text-sm font-medium">{t("Provider")}</label>
                <select
                  value={form.provider}
                  onChange={(e) => handleProviderChange(e.target.value)}
                  disabled={!!editingConnector}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                >
                  <optgroup label={t("Databases")}>
                    <option value="postgresql">PostgreSQL</option>
                    <option value="oracle">Oracle</option>
                    <option value="sqlserver">SQL Server</option>
                    <option value="mysql">MySQL</option>
                  </optgroup>
                  <optgroup label={t("Cloud Storage")}>
                    <option value="azure_blob">Azure Blob Storage</option>
                    <option value="sharepoint">SharePoint</option>
                  </optgroup>
                  {ENABLE_OUTLOOK_CONNECTOR && (
                  <optgroup label={t("Email")}>
                    <option value="outlook">Microsoft Outlook</option>
                  </optgroup>
                  )}
                </select>
              </div>

              {/* ── DB provider fields ── */}
              {isDbProvider(form.provider) && (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="col-span-2">
                      <label className="mb-1.5 block text-sm font-medium">{t("Host")}</label>
                      <input
                        value={form.host}
                        onChange={(e) => setForm({ ...form, host: e.target.value })}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder={DEFAULT_CONNECTOR_HOST}
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Port")}</label>
                      <input
                        type="number"
                        value={form.port}
                        onChange={(e) =>
                          setForm({ ...form, port: parseInt(e.target.value) || 0 })
                        }
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Database Name")}</label>
                      <input
                        value={form.database_name}
                        onChange={(e) => setForm({ ...form, database_name: e.target.value })}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="my_database"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Schema")}</label>
                      <input
                        value={form.schema_name}
                        onChange={(e) => setForm({ ...form, schema_name: e.target.value })}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="public"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Username")}</label>
                      <input
                        value={form.username}
                        onChange={(e) => setForm({ ...form, username: e.target.value })}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="db_user"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Password")}</label>
                      <div className="relative">
                        <input
                          type={showPassword ? "text" : "password"}
                          value={form.password}
                          onChange={(e) => setForm({ ...form, password: e.target.value })}
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 pr-10 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                          placeholder={editingConnector ? t("(unchanged)") : t("password")}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        >
                          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  </div>

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.ssl_enabled}
                      onChange={(e) => setForm({ ...form, ssl_enabled: e.target.checked })}
                      className="rounded border-border"
                    />
                    {t("Enable SSL/TLS")}
                  </label>
                </>
              )}

              {/* ── Azure Blob fields ── */}
              {form.provider === "azure_blob" && (
                <>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium">{t("Storage Account URL")}</label>
                    <input
                      value={form.azure_account_url}
                      onChange={(e) =>
                        setForm({ ...form, azure_account_url: e.target.value })
                      }
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                      placeholder="https://<account>.blob.core.windows.net"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Container Name")}</label>
                      <input
                        value={form.azure_container_name}
                        onChange={(e) =>
                          setForm({ ...form, azure_container_name: e.target.value })
                        }
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="my-container"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">
                        {t("Blob Prefix")}{" "}
                        <span className="text-xs text-muted-foreground">{t("(optional)")}</span>
                      </label>
                      <input
                        value={form.azure_blob_prefix}
                        onChange={(e) =>
                          setForm({ ...form, azure_blob_prefix: e.target.value })
                        }
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="folder/subfolder/"
                      />
                    </div>
                  </div>
                </>
              )}

              {/* ── SharePoint fields ── */}
              {form.provider === "sharepoint" && (
                <>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium">{t("SharePoint Site URL")}</label>
                    <input
                      value={form.sharepoint_site_url}
                      onChange={(e) =>
                        setForm({ ...form, sharepoint_site_url: e.target.value })
                      }
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                      placeholder="https://contoso.sharepoint.com/sites/MySite"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Document Library")}</label>
                      <input
                        value={form.sharepoint_library}
                        onChange={(e) =>
                          setForm({ ...form, sharepoint_library: e.target.value })
                        }
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="Shared Documents"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">
                        {t("Folder Path")}{" "}
                        <span className="text-xs text-muted-foreground">{t("(optional)")}</span>
                      </label>
                      <input
                        value={form.sharepoint_folder}
                        onChange={(e) =>
                          setForm({ ...form, sharepoint_folder: e.target.value })
                        }
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="Reports/2024"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">{t("Client ID")}</label>
                      <input
                        value={form.sharepoint_client_id}
                        onChange={(e) =>
                          setForm({ ...form, sharepoint_client_id: e.target.value })
                        }
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium">
                        {t("Client Secret")}{" "}
                        {editingConnector && (
                          <span className="text-xs text-muted-foreground">{t("(leave blank to keep current)")}</span>
                        )}
                      </label>
                      <div className="relative">
                        <input
                          type={showPassword ? "text" : "password"}
                          value={form.sharepoint_client_secret}
                          onChange={(e) =>
                            setForm({ ...form, sharepoint_client_secret: e.target.value })
                          }
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 pr-10 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                          placeholder={editingConnector ? t("(unchanged)") : t("client-secret")}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        >
                          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium">{t("Tenant ID")}</label>
                    <input
                      value={form.sharepoint_tenant_id}
                      onChange={(e) =>
                        setForm({ ...form, sharepoint_tenant_id: e.target.value })
                      }
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                      placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                    />
                  </div>

                  {/* Surface what this connector's app reg is actually
                      allowed to do. The probe runs an app-only token request
                      + a real list_drives() call, so users see the true
                      read/write state up-front instead of discovering it
                      after a failed upload. Only shown when editing an
                      existing connector (we need an ID to probe). */}
                  {editingConnector?.id && (
                    <SharePointCapabilityBanner connectorId={editingConnector.id} />
                  )}
                </>
              )}

              {/* ── Outlook fields ── */}
              {form.provider === "outlook" && (
                <OutlookConnectorForm
                  form={form}
                  onChange={(field, value) => setForm({ ...form, [field]: value })}
                  isEditing={!!editingConnector}
                  connectorId={editingConnector?.id}
                />
              )}

              {/* Test Result */}
              {testResult && (
                <div
                  className={`flex items-center gap-2 rounded-lg px-4 py-3 text-sm ${
                    testResult.success
                      ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                      : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                  }`}
                >
                  {testResult.success ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  {testResult.message}
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="mt-6 flex justify-end gap-3 border-t pt-4">
              <button
                onClick={handleModalTestConnection}
                disabled={testDraftMutation.isPending || testMutation.isPending || updateMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted transition-colors disabled:opacity-50"
              >
                {(testDraftMutation.isPending || testMutation.isPending) && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {t("Test Connection")}
              </button>
              <button
                onClick={() => {
                  setShowModal(false);
                  resetForm();
                }}
                className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted transition-colors"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={handleSave}
                disabled={isSaveDisabled()}
                className="inline-flex items-center gap-2 rounded-lg  px-4 py-2 text-sm font-medium !bg-[var(--button-primary)] hover:!bg-[var(--button-primary-hover)] disabled:!bg-[var(--button-primary-disabled)] text-primary-foreground "
              >
                {(createMutation.isPending || updateMutation.isPending) && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {editingConnector ? t("Update") : t("Create")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-xl">
            <h3 className="mb-2 text-lg font-semibold">{t("Delete Connector")}</h3>
            <p className="mb-6 text-sm text-muted-foreground">
              {t("Are you sure you want to delete this connector? This action cannot be undone.")}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted transition-colors"
              >
                {t("Cancel")}
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={deleteMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50 transition-colors"
              >
                {deleteMutation.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {t("Delete")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
