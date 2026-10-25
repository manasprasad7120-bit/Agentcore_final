import { useContext, useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import type {
  ModelType,
  ModelTypeFilter,
  ModelCreateRequest,
  ModelUpdateRequest,
  ModelEnvironment,
} from "@/types/models/models";
import useAlertStore from "@/stores/alertStore";
import {
  usePostRegistryModel,
  usePutRegistryModel,
  useTestModelConnection,
  usePromoteRegistryModel,
  useChangeModelVisibility,
} from "@/controllers/API/queries/models";

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "azure", label: "Azure" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google (AI Studio)" },
  { value: "google_vertex", label: "Google (Vertex AI)" },
  { value: "groq", label: "Groq" },
  { value: "openai_compatible", label: "Custom Model" },
];

const DEFAULT_AZURE_API_VERSION = "2025-10-01-preview";

const ENVIRONMENTS: { value: ModelEnvironment; label: string }[] = [
  { value: "uat", label: "UAT" },
  { value: "prod", label: "PROD" },
];

type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
};

interface EditModelModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  model?: ModelType | null;
  modelType?: ModelTypeFilter;
}

export default function EditModelModal({
  open,
  onOpenChange,
  model,
  modelType = "llm",
}: EditModelModalProps) {
  const { t } = useTranslation();
  const { role } = useContext(AuthContext);
  const normalizedRole = String(role || "").toLowerCase();
  const canMultiDept = normalizedRole === "super_admin" || normalizedRole === "root";
  const isDeptAdmin = normalizedRole === "department_admin";
  const isEditMode = !!model;

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const createMutation = usePostRegistryModel();
  const updateMutation = usePutRegistryModel();
  const testMutation = useTestModelConnection();
  const promoteMutation = usePromoteRegistryModel();
  const visibilityMutation = useChangeModelVisibility();

  /* ---------------------------------- Form State ---------------------------------- */

  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("");
  const [description, setDescription] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [environmentSelection, setEnvironmentSelection] = useState<"uat" | "prod" | "both">("uat");
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">("private");
  const [orgId, setOrgId] = useState("");
  const [deptId, setDeptId] = useState("");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });
  const [isActive, setIsActive] = useState(true);

  // Provider-specific
  const [azureDeployment, setAzureDeployment] = useState("");
  const [azureApiVersion, setAzureApiVersion] = useState(DEFAULT_AZURE_API_VERSION);
  const [vertexProjectId, setVertexProjectId] = useState("");
  const [vertexLocation, setVertexLocation] = useState("us-central1");
  const [customHeaders, setCustomHeaders] = useState("");
  const [showInOrchestrator, setShowInOrchestrator] = useState(true);
  const [showInAgent, setShowInAgent] = useState(true);

  // Default params (LLM)
  const [temperature, setTemperature] = useState<number | "">("");
  const [maxTokens, setMaxTokens] = useState<number | "">("");

  // Per-model rate limits. Empty string = unlimited (no cap sent to backend).
  const [rateLimitRpm, setRateLimitRpm] = useState<number | "">("");
  const [rateLimitTpm, setRateLimitTpm] = useState<number | "">("");

  // Embedding-specific
  const [dimensions, setDimensions] = useState<number | "">("");
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
    latency_ms?: number | null;
  } | null>(null);
  const [testPayloadKey, setTestPayloadKey] = useState<string | null>(null);

  const departmentsForSelectedOrg = useMemo(
    () => visibilityOptions.departments.filter((d) => !orgId || d.org_id === orgId),
    [visibilityOptions.departments, orgId],
  );
  const selectedDeptLabel = useMemo(() => {
    if (publicDeptIds.length === 0) return t("Select departments");
    const names = departmentsForSelectedOrg
      .filter((dept) => publicDeptIds.includes(dept.id))
      .map((dept) => dept.name);
    if (names.length === 0) return t("Select departments");
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [departmentsForSelectedOrg, publicDeptIds]);

  const isEmbedding = modelType === "embedding" || model?.model_type === "embedding";

  /* ---------------------------------- Populate form on edit ---------------------------------- */

  useEffect(() => {
    if (!open) return;

    if (model) {
      setDisplayName(model.display_name);
      setProvider(model.provider);
      setModelName(model.model_name);
      setDescription(model.description ?? "");
      setApiKey(""); // never pre-fill
      setBaseUrl(model.base_url ?? "");
      const normalizeEnv = (env: string) => (env === "test" ? "uat" : env);
      const modelEnvs = (model.environments ?? []).map((env) => normalizeEnv(String(env).toLowerCase()));
      if (modelEnvs.includes("uat") && modelEnvs.includes("prod")) {
        setEnvironmentSelection("both");
      } else {
        const fallbackEnv = normalizeEnv(String(model.environment ?? "uat").toLowerCase());
        setEnvironmentSelection((fallbackEnv || "uat") as "uat" | "prod");
      }
      setVisibilityScope(model.visibility_scope ?? "private");
      setOrgId(model.org_id ?? "");
      setDeptId(model.dept_id ?? "");
      setPublicDeptIds(
        model.public_dept_ids && model.public_dept_ids.length > 0
          ? model.public_dept_ids
          : model.dept_id
            ? [model.dept_id]
            : [],
      );
      setIsActive(model.is_active);

      const pc = model.provider_config ?? {};
      setAzureDeployment(pc.azure_deployment ?? "");
      setAzureApiVersion(pc.api_version ?? DEFAULT_AZURE_API_VERSION);
      setVertexProjectId(pc.project_id ?? "");
      setVertexLocation(pc.location ?? "us-central1");
      setCustomHeaders(pc.custom_headers ? JSON.stringify(pc.custom_headers, null, 2) : "");
      const si = (model as any).show_in || ["orchestrator", "agent"];
      setShowInOrchestrator(si.includes("orchestrator"));
      setShowInAgent(si.includes("agent"));

      const dp = model.default_params ?? {};
      setTemperature(dp.temperature ?? "");
      setMaxTokens(dp.max_tokens ?? "");
      setDimensions(dp.dimensions ?? "");
      setRateLimitRpm((model as any).rate_limit_rpm ?? "");
      setRateLimitTpm((model as any).rate_limit_tpm ?? "");
    } else {
      // Reset for create
      setDisplayName("");
      setProvider("openai");
      setModelName("");
      setDescription("");
      setApiKey("");
      setBaseUrl("");
      setEnvironmentSelection("uat");
      setVisibilityScope("private");
      setOrgId("");
      setDeptId("");
      setPublicDeptIds([]);
      setIsActive(true);
      setAzureDeployment("");
      setAzureApiVersion(DEFAULT_AZURE_API_VERSION);
      setVertexProjectId("");
      setVertexLocation("us-central1");
      setCustomHeaders("");
      setShowInOrchestrator(true);
      setShowInAgent(true);
      setTemperature("");
      setMaxTokens("");
      setDimensions("");
      setRateLimitRpm("");
      setRateLimitTpm("");
    }
    setTestResult(null);
    setTestPayloadKey(null);
  }, [model, open]);

  useEffect(() => {
    if (!open) return;
    api.get("api/models/registry/visibility-options").then((res) => {
      const options: VisibilityOptions = res.data || {
        organizations: [],
        departments: [],
      };
      setVisibilityOptions(options);
      if (!orgId) setOrgId(options.organizations?.[0]?.id || "");
      if (!deptId) setDeptId(options.departments?.[0]?.id || "");
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if ((normalizedRole === "developer" || normalizedRole === "department_admin") && visibilityOptions.departments.length > 0) {
      const firstDept = visibilityOptions.departments[0];
      if (!deptId) setDeptId(firstDept.id);
      if (!orgId) setOrgId(firstDept.org_id);
      if (publicDeptIds.length === 0) setPublicDeptIds([firstDept.id]);
    }
  }, [open, normalizedRole, visibilityOptions, deptId, orgId, publicDeptIds]);

  useEffect(() => {
    if (!open) return;
    if (visibilityScope === "organization") {
      const firstOrg =
        visibilityOptions.organizations[0]?.id ||
        visibilityOptions.departments[0]?.org_id ||
        "";
      if (!orgId && firstOrg) setOrgId(firstOrg);
      return;
    }
    if (visibilityScope !== "department") return;
    const firstDept = departmentsForSelectedOrg[0] || visibilityOptions.departments[0];
    if (!firstDept) return;
    if (canMultiDept) {
      const hasSelectedDept = publicDeptIds.some((id) =>
        departmentsForSelectedOrg.some((dept) => dept.id === id),
      );
      if (!orgId) setOrgId(firstDept.org_id);
      if (!hasSelectedDept) setPublicDeptIds([firstDept.id]);
      return;
    }
    if (!deptId) setDeptId(firstDept.id);
    if (!orgId) setOrgId(firstDept.org_id);
  }, [
    open,
    visibilityScope,
    canMultiDept,
    orgId,
    deptId,
    publicDeptIds,
    departmentsForSelectedOrg,
    visibilityOptions.organizations,
    visibilityOptions.departments,
  ]);

  useEffect(() => {
    if (!open) return;
    const key = buildTestKey();
    if (testPayloadKey && key !== testPayloadKey) {
      setTestResult(null);
      setTestPayloadKey(null);
    }
  }, [
    open,
    provider,
    modelName,
    baseUrl,
    apiKey,
    azureDeployment,
    azureApiVersion,
    customHeaders,
    isEmbedding,
    testPayloadKey,
  ]);

  /* ---------------------------------- Build payload ---------------------------------- */

  const buildProviderConfig = (): Record<string, any> | undefined => {
    const config: Record<string, any> = {};
    if (provider === "azure") {
      if (azureDeployment) config.azure_deployment = azureDeployment;
      if (azureApiVersion) config.api_version = azureApiVersion;
    }
    if (provider === "google_vertex") {
      if (vertexProjectId) config.project_id = vertexProjectId;
      if (vertexLocation) config.location = vertexLocation;
    }
    if (provider === "openai_compatible" && customHeaders) {
      try {
        config.custom_headers = JSON.parse(customHeaders);
      } catch {
        /* ignore parse errors */
      }
    }
    return Object.keys(config).length ? config : undefined;
  };

  const buildDefaultParams = () => {
    const params: Record<string, any> = {};
    if (!isEmbedding) {
      if (temperature !== "") params.temperature = Number(temperature);
      if (maxTokens !== "") params.max_tokens = Number(maxTokens);
    }
    if (isEmbedding && dimensions !== "") {
      params.dimensions = Number(dimensions);
    }
    return Object.keys(params).length ? params : undefined;
  };

  const buildShowIn = (): string[] | null => {
    const arr: string[] = [];
    if (showInOrchestrator) arr.push("orchestrator");
    if (showInAgent) arr.push("agent");
    return arr.length > 0 ? arr : null;
  };

  const buildTestPayload = () => ({
    provider,
    model_name: modelName,
    base_url: baseUrl || null,
    api_key: apiKey || null,
    provider_config: buildProviderConfig() ?? null,
    isEmbedding,
  });

  const buildTestKey = () => JSON.stringify(buildTestPayload());

  const sortObjectKeys = (value: any): any => {
    if (Array.isArray(value)) {
      return value.map(sortObjectKeys);
    }
    if (value && typeof value === "object") {
      return Object.keys(value)
        .sort()
        .reduce((acc, key) => {
          acc[key] = sortObjectKeys(value[key]);
          return acc;
        }, {} as Record<string, any>);
    }
    return value;
  };

  const isSameValue = (a: any, b: any) => {
    const normalize = (v: any) => (v === undefined ? null : v);
    const left = normalize(a);
    const right = normalize(b);
    if (typeof left === "object" || typeof right === "object") {
      return JSON.stringify(sortObjectKeys(left)) === JSON.stringify(sortObjectKeys(right));
    }
    return left === right;
  };

  /* ---------------------------------- Handlers ---------------------------------- */

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      if (isEditMode && model) {
        const normalizeEnv = (env: string) => (env === "test" ? "uat" : env);
        const originalEnvs = (model.environments ?? []).map((env) => normalizeEnv(String(env).toLowerCase()));
        const effectiveOriginalEnvs = originalEnvs.length
          ? originalEnvs
          : [normalizeEnv(String(model.environment ?? "uat").toLowerCase())];
        const originalEnvironment = effectiveOriginalEnvs[0] ?? "uat";
        const originalVisibility = model.visibility_scope ?? "private";
        const originalProviderConfig = model.provider_config ?? null;
        const originalDefaultParams = model.default_params ?? null;
        const desiredEnvs =
          environmentSelection === "both" ? ["uat", "prod"] : [environmentSelection];
        const desiredEnvironment = desiredEnvs[0];

        const payload: ModelUpdateRequest = {
          display_name: displayName,
          description: description || null,
          provider,
          model_name: modelName,
          model_type: isEmbedding ? "embedding" : "llm",
          base_url: baseUrl || null,
          provider_config: buildProviderConfig() ?? null,
          default_params: buildDefaultParams() ?? null,
          show_in: buildShowIn(),
          is_active: isActive,
          rate_limit_rpm: rateLimitRpm === "" ? null : Number(rateLimitRpm),
          rate_limit_tpm: rateLimitTpm === "" ? null : Number(rateLimitTpm),
        };
        if (apiKey) payload.api_key = apiKey;

        const desiredProviderConfig = buildProviderConfig() ?? null;
        const desiredDefaultParams = buildDefaultParams() ?? null;
        const basePayloadChanged =
          !isSameValue(payload.display_name, model.display_name) ||
          !isSameValue(payload.description, model.description ?? null) ||
          !isSameValue(payload.provider, model.provider) ||
          !isSameValue(payload.model_name, model.model_name) ||
          !isSameValue(payload.model_type, model.model_type) ||
          !isSameValue(payload.base_url, model.base_url ?? null) ||
          !isSameValue(payload.provider_config ?? null, originalProviderConfig) ||
          !isSameValue(payload.default_params ?? null, originalDefaultParams) ||
          !isSameValue(payload.is_active, model.is_active) ||
          !isSameValue(payload.rate_limit_rpm ?? null, (model as any).rate_limit_rpm ?? null) ||
          !isSameValue(payload.rate_limit_tpm ?? null, (model as any).rate_limit_tpm ?? null);

        const normalizedOriginal = Array.from(new Set(effectiveOriginalEnvs)).sort();
        const normalizedDesired = Array.from(new Set(desiredEnvs)).sort();
        const environmentChanged =
          normalizedOriginal.length !== normalizedDesired.length ||
          normalizedOriginal.some((env, idx) => env !== normalizedDesired[idx]);

        const desiredPublicDeptIds =
          visibilityScope === "department"
            ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : [])
            : [];
        const normalizedOriginalPublicDeptIds = (model.public_dept_ids || []).map(String).sort();
        const normalizedDesiredPublicDeptIds = desiredPublicDeptIds.map(String).sort();
        const publicDeptsChanged =
          normalizedOriginalPublicDeptIds.length !== normalizedDesiredPublicDeptIds.length ||
          normalizedOriginalPublicDeptIds.some((id, idx) => id !== normalizedDesiredPublicDeptIds[idx]);
        const desiredOrgId = orgId || null;
        const desiredDeptId =
          visibilityScope === "department" ? (canMultiDept ? null : deptId || null) : null;
        const scopeChanged =
          visibilityScope !== originalVisibility ||
          (model.org_id || null) !== desiredOrgId ||
          (model.dept_id || null) !== desiredDeptId ||
          publicDeptsChanged;

        const hasChanges =
          basePayloadChanged ||
          environmentChanged ||
          scopeChanged ||
          Boolean(apiKey);

        if (!hasChanges) {
          setErrorData({
            title: t("No changes detected"),
            list: [t("Update at least one field before saving.")],
          });
          return;
        }

        await updateMutation.mutateAsync({ id: model.id, data: payload });

        if (environmentChanged) {
          const isPromotion = !normalizedOriginal.includes("prod") && normalizedDesired.includes("prod");
          if (!isPromotion) {
            setErrorData({
              title: t("Environment change not allowed"),
              list: [t("Removing environments is not supported. Only UAT to PROD promotion is allowed.")],
            });
            return;
          }
          await promoteMutation.mutateAsync({
            id: model.id,
            target_environment: "prod",
          });
        }

        if (scopeChanged) {
          await visibilityMutation.mutateAsync({
            id: model.id,
            visibility_scope: visibilityScope,
            org_id: desiredOrgId,
            dept_id: desiredDeptId,
            public_dept_ids: desiredPublicDeptIds,
          });
        }

        setSuccessData({
          title: t('Model "{{name}}" updated.', { name: displayName }),
          list:
            environmentChanged || scopeChanged
              ? [
                  t("Changes that affect environment or visibility may require approval. Check Review & Approval for status."),
                ]
              : undefined,
        });
      } else {
        const currentTestKey = buildTestKey();
        let connectionResult =
          testResult && testPayloadKey === currentTestKey ? testResult : null;
        let autoTestRan = false;
        if (!connectionResult) {
          connectionResult = await testMutation.mutateAsync(buildTestPayload());
          setTestResult(connectionResult);
          setTestPayloadKey(currentTestKey);
          autoTestRan = true;
        }
        if (!connectionResult.success) {
          const message = connectionResult.message || t("Connection test failed.");
          setErrorData({
            title: t("Connection test failed"),
            list: [message],
          });
          return;
        }
        if (autoTestRan) {
          setSuccessData({
            title: t("Connection successful{{latency}}", {
              latency: connectionResult.latency_ms ? ` (${connectionResult.latency_ms}ms)` : "",
            }),
          });
        }

        const desiredEnvs =
          environmentSelection === "both" ? ["uat", "prod"] : [environmentSelection];
        const desiredEnvironment = desiredEnvs[0];
        const payload: ModelCreateRequest = {
          display_name: displayName,
          description: description || null,
          provider,
          model_name: modelName,
          model_type: isEmbedding ? "embedding" : "llm",
          base_url: baseUrl || null,
          api_key: apiKey || null,
          environment: desiredEnvironment,
          environments: desiredEnvs,
          visibility_scope: visibilityScope,
          org_id: visibilityScope === "organization" ? orgId || null : null,
          dept_id: visibilityScope === "department" ? (canMultiDept ? null : deptId || null) : null,
          public_dept_ids:
            visibilityScope === "department"
              ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : [])
              : [],
          provider_config: buildProviderConfig() ?? null,
          default_params: buildDefaultParams() ?? null,
          show_in: buildShowIn(),
          is_active: isActive,
          rate_limit_rpm: rateLimitRpm === "" ? null : Number(rateLimitRpm),
          rate_limit_tpm: rateLimitTpm === "" ? null : Number(rateLimitTpm),
        };

        await createMutation.mutateAsync(payload);
        const envLabel =
          environmentSelection === "both" ? "UAT + PROD" : environmentSelection.toUpperCase();
        setSuccessData({
          title: t('{{type}} "{{name}}" created.', {
            type: isEmbedding ? t("Embedding") : t("Model"),
            name: displayName,
          }),
          list: [
            t("Target environment: {{env}}.", { env: envLabel }),
            t("If approval is required, you'll see it in Review & Approval."),
          ],
        });
      }
      onOpenChange(false);
    } catch (err: any) {
      setErrorData({
        title: isEditMode ? t("Model update failed") : t("Model creation failed"),
        list: [err?.message ?? String(err)],
      });
    }
  };

  const handleTestConnection = async () => {
    try {
      const result = await testMutation.mutateAsync(buildTestPayload());
      setTestResult(result);
      setTestPayloadKey(buildTestKey());
      if (result.success) {
        setSuccessData({
          title: t("Connection successful{{latency}}", {
            latency: result.latency_ms ? ` (${result.latency_ms}ms)` : "",
          }),
        });
      } else {
        setErrorData({ title: t("Connection failed"), list: [result.message] });
      }
    } catch (err: any) {
      setTestResult({ success: false, message: err?.message ?? String(err) });
      setTestPayloadKey(buildTestKey());
      setErrorData({
        title: t("Connection test failed"),
        list: [err?.message ?? String(err)],
      });
    }
  };

  const handleClose = () => onOpenChange(false);

  const isSaving =
    createMutation.isPending ||
    updateMutation.isPending ||
    promoteMutation.isPending ||
    visibilityMutation.isPending;
  const canTest = !!modelName && !!apiKey;

  if (!open) return null;

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-0 overflow-hidden p-0">
        {/* Header */}
        <div className="flex-shrink-0 border-b p-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold">
                {isEditMode
                  ? isEmbedding ? t("Edit Embedding Model") : t("Edit Model")
                  : isEmbedding ? t("Add Embedding Model") : t("Add Model")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {isEditMode
                  ? isEmbedding ? t("Update embedding model configuration") : t("Update model configuration and settings")
                  : isEmbedding ? t("Onboard a new embedding model to the registry") : t("Onboard a new AI model to the registry")}
              </p>
            </div>
          </div>
        </div>

        {/* Scrollable Form Body */}
        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto p-6 space-y-6"
        >
          {/* ========== BASIC INFO ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Basic Information")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Display Name")} *</Label>
                <Input
                  required
                  placeholder={t("e.g., GPT-4o PROD")}
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>
              <div>
                <Label>{t("Provider")} *</Label>
                <select
                  required
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <Label>{t("Description")}</Label>
              <Textarea
                rows={2}
                placeholder={t("Brief description of this model configuration")}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </fieldset>

          {/* ========== CONNECTION ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Connection")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Model Name / ID")} *</Label>
                <Input
                  required
                  placeholder={t("e.g., gpt-4o, claude-3-opus-20240229")}
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
              </div>
              <div>
                <Label>{t("API Key")} {!isEditMode && "*"}</Label>
                <Input
                  type="password"
                  required={!isEditMode}
                  placeholder={isEditMode ? t("(unchanged)") : t("sk-...")}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <p className="mt-1 text-xxs text-muted-foreground">
                  {t("Encrypted before storage. Never exposed in responses.")}
                </p>
              </div>
            </div>

            <div>
              <Label>
                {t("Base URL")}
                {(provider === "azure" || provider === "openai_compatible") &&
                  " *"}
              </Label>
              <Input
                required={
                  provider === "azure" || provider === "openai_compatible"
                }
                placeholder={
                  provider === "azure"
                    ? t("https://your-resource.openai.azure.com/")
                    : t("https://api.example.com/v1")
                }
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>

            {/* Azure-specific */}
            {provider === "azure" && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>{t("Deployment Name")} *</Label>
                  <Input
                    required
                    placeholder={t("my-gpt4-deployment")}
                    value={azureDeployment}
                    onChange={(e) => setAzureDeployment(e.target.value)}
                  />
                </div>
                <div>
                  <Label>{t("API Version")}</Label>
                  <Input
                    placeholder={t("2025-10-01-preview")}
                    value={azureApiVersion}
                    onChange={(e) => setAzureApiVersion(e.target.value)}
                  />
                </div>
              </div>
            )}

            {/* Vertex AI-specific */}
            {provider === "google_vertex" && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>{t("Project ID")} *</Label>
                  <Input
                    required
                    placeholder={t("my-gcp-project-id")}
                    value={vertexProjectId}
                    onChange={(e) => setVertexProjectId(e.target.value)}
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("Google Cloud project ID")}
                  </p>
                </div>
                <div>
                  <Label>{t("Location")}</Label>
                  <Input
                    placeholder={t("us-central1")}
                    value={vertexLocation}
                    onChange={(e) => setVertexLocation(e.target.value)}
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("Vertex AI region (default: us-central1)")}
                  </p>
                </div>
              </div>
            )}

            {/* Custom headers */}
            {provider === "openai_compatible" && (
              <div>
                <Label>{t("Custom Headers (JSON)")}</Label>
                <Textarea
                  rows={3}
                  placeholder={t('{"X-Custom-Header": "value"}')}
                  value={customHeaders}
                  onChange={(e) => setCustomHeaders(e.target.value)}
                />
              </div>
            )}
          </fieldset>

          {/* ========== ENVIRONMENT ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Environment & Tenancy")}
            </legend>
            <div className="flex gap-3">
              {[...ENVIRONMENTS, { value: "both" as const, label: t("UAT + PROD") }].map((env) => (
                <button
                  key={env.value}
                  type="button"
                  onClick={() => setEnvironmentSelection(env.value as "uat" | "prod" | "both")}
                  className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                    environmentSelection === env.value
                      ? "border-[var(--button-primary)] bg-[var(--button-primary)] text-[var(--button-primary-foreground)]"
                      : "border-input bg-background hover:bg-muted"
                  }`}
                >
                  {env.label}
                </button>
              ))}
            </div>
            <p className="text-xxs text-muted-foreground">
              {isEditMode
                ? t("Changing environment here will submit a promotion request when applicable.")
                : t("Models default to UAT. Selecting UAT + PROD submits a single approval for both environments.")}
            </p>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Visibility Scope")}</Label>
                <select
                  value={visibilityScope}
                  onChange={(e) =>
                    setVisibilityScope(e.target.value as "private" | "department" | "organization")
                  }
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="private">{t("private")}</option>
                  <option value="department">{t("department")}</option>
                  <option value="organization">{t("organization")}</option>
                </select>
              </div>
              {visibilityScope === "organization" ? (
                <div>
                  <Label>{t("Organization")}</Label>
                  <select
                    value={orgId}
                    onChange={(e) => setOrgId(e.target.value)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    disabled={normalizedRole === "developer" || normalizedRole === "department_admin"}
                  >
                    <option value="">{t("Select organization")}</option>
                    {visibilityOptions.organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </div>
              ) : visibilityScope === "department" ? (
                <div>
                  <Label>{canMultiDept ? t("Departments") : t("Department")}</Label>
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
                            checked={publicDeptIds.includes(dept.id)}
                            onSelect={(event) => event.preventDefault()}
                            onCheckedChange={(checked) => {
                              setPublicDeptIds((prev) =>
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
                    <select
                      value={deptId}
                      onChange={(e) => setDeptId(e.target.value)}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      disabled={normalizedRole === "developer" || normalizedRole === "department_admin"}
                    >
                      <option value="">{t("Select department")}</option>
                      {departmentsForSelectedOrg.map((dept) => (
                        <option key={dept.id} value={dept.id}>
                          {dept.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              ) : (
                <div />
              )}
            </div>
            {isEditMode && (
              <p className="text-xxs text-muted-foreground">
                {t("Visibility changes here will submit approval requests when required.")}
              </p>
            )}
          </fieldset>

          {/* ========== AVAILABILITY ========== */}
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Availability")}
            </legend>
            <p className="text-xs text-muted-foreground">
              {t("Choose where this model should appear")}
            </p>
            <div className="flex flex-col gap-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showInOrchestrator}
                  onChange={(e) => {
                    if (!e.target.checked && !showInAgent) return; // at least one must be checked
                    setShowInOrchestrator(e.target.checked);
                  }}
                  className="h-4 w-4 rounded border-border"
                />
                {t("Orchestrator Chat")}
                <span className="text-xs text-muted-foreground">({t("direct model chat")})</span>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showInAgent}
                  onChange={(e) => {
                    if (!e.target.checked && !showInOrchestrator) return; // at least one must be checked
                    setShowInAgent(e.target.checked);
                  }}
                  className="h-4 w-4 rounded border-border"
                />
                {t("Agent Canvas")}
                <span className="text-xs text-muted-foreground">({t("for building agents")})</span>
              </label>
            </div>
          </fieldset>

          {/* ========== DEFAULT PARAMS ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {isEmbedding ? t("Embedding Parameters") : t("Default Parameters")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              {!isEmbedding && (
                <>
                  <div>
                    <Label>{t("Temperature (0-2)")}</Label>
                    <Input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      placeholder={t("Optional")}
                      value={temperature}
                      onChange={(e) =>
                        setTemperature(
                          e.target.value ? Number(e.target.value) : "",
                        )
                      }
                    />
                  </div>
                  <div>
                    <Label>{t("Max Output Tokens")}</Label>
                    <Input
                      type="number"
                      placeholder={t("4096")}
                      value={maxTokens}
                      onChange={(e) =>
                        setMaxTokens(e.target.value ? Number(e.target.value) : "")
                      }
                    />
                  </div>
                </>
              )}
              {isEmbedding && (
                <div>
                  <Label>{t("Dimensions")}</Label>
                  <Input
                    type="number"
                    placeholder={t("e.g., 1536")}
                    value={dimensions}
                    onChange={(e) =>
                      setDimensions(e.target.value ? Number(e.target.value) : "")
                    }
                  />
                  <p className="mt-1 text-xxs text-muted-foreground">
                    {t("Leave empty to use the model's default dimension.")}
                  </p>
                </div>
              )}
            </div>
          </fieldset>

          {/* ========== RATE LIMITS ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Rate Limits")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Requests per minute")}</Label>
                <Input
                  type="number"
                  min="0"
                  placeholder={t("Unlimited")}
                  value={rateLimitRpm}
                  onChange={(e) =>
                    setRateLimitRpm(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
              <div>
                <Label>{t("Tokens per minute")}</Label>
                <Input
                  type="number"
                  min="0"
                  placeholder={t("Unlimited")}
                  value={rateLimitTpm}
                  onChange={(e) =>
                    setRateLimitTpm(e.target.value ? Number(e.target.value) : "")
                  }
                />
              </div>
            </div>
            <p className="text-xxs text-muted-foreground">
              {t(
                "Leave blank for unlimited. TPM is debited from actual provider token usage; a single large request may temporarily overshoot the limit before subsequent requests are blocked.",
              )}
            </p>
          </fieldset>

          {/* ========== STATUS ========== */}
          <fieldset className="space-y-2">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Status")}
            </legend>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              {t("Active")}
            </label>
            <p className="text-xxs text-muted-foreground">
              {t("Inactive models won't appear in the agent builder component dropdown.")}
            </p>
          </fieldset>
        </form>

        {/* Footer */}
        <div className="flex-shrink-0 border-t p-6">
          <div className="flex items-center gap-3">
            {/* Test Connection */}
            <Button
              type="button"
              variant="outline"
              disabled={!canTest || testMutation.isPending}
              onClick={handleTestConnection}
            >
              {testMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Zap className="mr-2 h-4 w-4" />
              )}
              {t("Test Connection")}
            </Button>

            <div className="flex-1" />

            <Button type="button" variant="outline" onClick={handleClose}>
              {t("Cancel")}
            </Button>
            <Button
              type="submit"
              disabled={isSaving}
              onClick={handleSubmit}
            >
              {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isEditMode ? t("Save Changes") : isEmbedding ? t("Add Embedding") : t("Add Model")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
