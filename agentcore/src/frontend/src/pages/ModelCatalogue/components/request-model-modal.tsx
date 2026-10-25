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
import {
  usePostRegistryModel,
  useTestModelConnection,
} from "@/controllers/API/queries/models";
import useAlertStore from "@/stores/alertStore";
import type { ModelTypeFilter } from "@/types/models/models";

interface RequestModelModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  modelType?: ModelTypeFilter;
}

interface VisibilityOptions {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
}

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "azure", label: "Azure OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google (AI Studio)" },
  { value: "google_vertex", label: "Google (Vertex AI)" },
  { value: "groq", label: "Groq" },
  { value: "openai_compatible", label: "Custom Model" },
];
const DEFAULT_AZURE_API_VERSION = "2025-10-01-preview";

export default function RequestModelModal({
  open,
  onOpenChange,
  modelType = "llm",
}: RequestModelModalProps) {
  const { t } = useTranslation();
  const { role } = useContext(AuthContext);
  const normalizedRole = String(role || "").toLowerCase();
  const canMultiDept = normalizedRole === "super_admin" || normalizedRole === "root";

  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [azureDeployment, setAzureDeployment] = useState("");
  const [azureApiVersion, setAzureApiVersion] = useState(DEFAULT_AZURE_API_VERSION);
  const [vertexProjectId, setVertexProjectId] = useState("");
  const [vertexLocation, setVertexLocation] = useState("us-central1");
  const [showInOrchestrator, setShowInOrchestrator] = useState(true);
  const [showInAgent, setShowInAgent] = useState(true);
  const [customHeaders, setCustomHeaders] = useState("");
  const [environmentSelection, setEnvironmentSelection] = useState<"uat" | "prod" | "both">("uat");
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">("private");
  const [deptId, setDeptId] = useState("");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });
  const [chargeCode, setChargeCode] = useState("");
  const [projectName, setProjectName] = useState("");
  const [reason, setReason] = useState("");
  const [temperature, setTemperature] = useState<number | "">("");
  const [maxTokens, setMaxTokens] = useState<number | "">("");
  const [dimensions, setDimensions] = useState<number | "">("");
  // Per-model rate limits. Empty string = unlimited (no cap sent to backend).
  const [rateLimitRpm, setRateLimitRpm] = useState<number | "">("");
  const [rateLimitTpm, setRateLimitTpm] = useState<number | "">("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
    latency_ms?: number | null;
  } | null>(null);
  const [testPayloadKey, setTestPayloadKey] = useState<string | null>(null);

  const createMutation = usePostRegistryModel();
  const testMutation = useTestModelConnection();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const isDirectAddPath = false;
  const isEmbedding = modelType === "embedding";

  const departmentsForSelectedOrg = useMemo(
    () => visibilityOptions.departments,
    [visibilityOptions.departments],
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
        // Keep submit behavior aligned with add modal: ignore invalid JSON here.
      }
    }
    return Object.keys(config).length ? config : undefined;
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

  const resetForm = () => {
    setDisplayName("");
    setProvider("openai");
    setModelName("");
    setBaseUrl("");
    setApiKey("");
    setAzureDeployment("");
    setAzureApiVersion(DEFAULT_AZURE_API_VERSION);
    setCustomHeaders("");
    setEnvironmentSelection("uat");
    setVisibilityScope("private");
    setDeptId("");
    setPublicDeptIds([]);
    setChargeCode("");
    setProjectName("");
    setReason("");
    setTemperature("");
    setMaxTokens("");
    setDimensions("");
    setRateLimitRpm("");
    setRateLimitTpm("");
    setTestResult(null);
    setTestPayloadKey(null);
  };

  useEffect(() => {
    if (!open) return;
    api.get("api/models/registry/visibility-options").then((res) => {
      const options: VisibilityOptions = res.data || {
        organizations: [],
        departments: [],
      };
      setVisibilityOptions(options);
      if (!deptId) setDeptId(options.departments?.[0]?.id || "");
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (
      (normalizedRole === "developer" || normalizedRole === "department_admin") &&
      visibilityOptions.departments.length > 0
    ) {
      const firstDept = visibilityOptions.departments[0];
      if (!deptId) setDeptId(firstDept.id);
      if (publicDeptIds.length === 0) setPublicDeptIds([firstDept.id]);
    }
  }, [open, normalizedRole, visibilityOptions, deptId, publicDeptIds]);

  useEffect(() => {
    if (!open || visibilityScope !== "department" || visibilityOptions.departments.length === 0) return;
    const firstDept = visibilityOptions.departments[0];
    if (canMultiDept) {
      const hasSelectedDept = publicDeptIds.some((id) =>
        visibilityOptions.departments.some((dept) => dept.id === id),
      );
      if (!hasSelectedDept) {
        setPublicDeptIds([firstDept.id]);
      }
      return;
    }
    if (!deptId) {
      setDeptId(firstDept.id);
    }
  }, [open, visibilityScope, canMultiDept, visibilityOptions.departments, deptId, publicDeptIds]);

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

  const handleClose = () => {
    onOpenChange(false);
    resetForm();
  };

  const handleTestConnection = async () => {
    if (!modelName.trim() || !apiKey.trim()) {
      setErrorData({
        title: t("Connection test failed"),
        list: [t("Model name and API key are required.")],
      });
      return;
    }
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) {
      setErrorData({ title: t("Submission failed"), list: [t("API key is required.")] });
      return;
    }
    if (!chargeCode.trim() || !projectName.trim() || !reason.trim()) {
      setErrorData({
        title: t("Submission failed"),
        list: [t("Charge code, project name, and reason are required.")],
      });
      return;
    }
    if (visibilityScope === "department" && !canMultiDept && !deptId) {
      setErrorData({
        title: t("Submission failed"),
        list: [t("Department is required for department visibility.")],
      });
      return;
    }
    if (visibilityScope === "department" && canMultiDept && publicDeptIds.length === 0) {
      setErrorData({
        title: t("Submission failed"),
        list: [t("Select at least one department for department visibility.")],
      });
      return;
    }

    const effectiveOrgId =
      visibilityOptions.departments.find((d) => d.id === (canMultiDept ? publicDeptIds[0] : deptId))?.org_id ||
      visibilityOptions.organizations[0]?.id ||
      null;
    const desiredEnvs = environmentSelection === "both" ? ["uat", "prod"] : [environmentSelection];
    const desiredEnvironment = desiredEnvs[0];

    setIsSubmitting(true);
    try {
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

      await createMutation.mutateAsync({
        display_name: displayName,
        description: reason,
        provider,
        model_name: modelName,
        model_type: isEmbedding ? "embedding" : "llm",
        base_url: baseUrl || null,
        api_key: apiKey || null,
        environment: desiredEnvironment,
        environments: desiredEnvs,
        visibility_scope: visibilityScope,
        org_id: visibilityScope === "organization" ? effectiveOrgId : null,
        dept_id: visibilityScope === "department" ? (canMultiDept ? null : deptId || null) : null,
        public_dept_ids: visibilityScope === "department" ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : []) : [],
        provider_config: {
          ...(buildProviderConfig() ?? {}),
          request_meta: {
            charge_code: chargeCode,
            project_name: projectName,
            reason,
          },
        },
        default_params: isEmbedding
          ? dimensions !== ""
            ? { dimensions: Number(dimensions) }
            : null
          : {
              ...(temperature !== "" ? { temperature: Number(temperature) } : {}),
              ...(maxTokens !== "" ? { max_tokens: Number(maxTokens) } : {}),
            },
        show_in: (() => {
          const arr: string[] = [];
          if (showInOrchestrator) arr.push("orchestrator");
          if (showInAgent) arr.push("agent");
          return arr.length > 0 ? arr : ["orchestrator", "agent"];
        })(),
        is_active: true,
        rate_limit_rpm: rateLimitRpm === "" ? null : Number(rateLimitRpm),
        rate_limit_tpm: rateLimitTpm === "" ? null : Number(rateLimitTpm),
      });
      setSuccessData({
        title: isDirectAddPath ? t("Model created") : t("Model request submitted"),
        list: isDirectAddPath
          ? [t("If approval is required, you'll see it in Review & Approval.")]
          : [t("Your request has been sent for approval.")],
      });
      handleClose();
    } catch (err: any) {
      setErrorData({
        title: t("Submission failed"),
        list: [err?.message ?? String(err)],
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <div className="flex-shrink-0 border-b p-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold">
                {isEmbedding ? t("Request Embedding") : t("Request Model")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("Configure the model and submit. Requests route based on environment and visibility.")}
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 space-y-6 overflow-y-auto p-6">
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Basic Information")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Display Name")} *</Label>
                <Input
                  required
                  placeholder={t("e.g., GPT-4.1 for Analytics")}
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

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Model Name / ID")} *</Label>
                <Input
                  required
                  placeholder={t("e.g., gpt-4.1-mini")}
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
              </div>
              <div>
                <Label>
                  {t("Base URL")}
                  {(provider === "azure" || provider === "openai_compatible") && " *"}
                </Label>
                <Input
                  required={provider === "azure" || provider === "openai_compatible"}
                  placeholder={
                    provider === "azure"
                      ? t("https://your-resource.openai.azure.com/")
                      : t("https://api.example.com/v1")
                  }
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </div>
            </div>

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
                  <p className="mt-1 text-xs text-muted-foreground">{t("Google Cloud project ID")}</p>
                </div>
                <div>
                  <Label>{t("Location")}</Label>
                  <Input
                    placeholder={t("us-central1")}
                    value={vertexLocation}
                    onChange={(e) => setVertexLocation(e.target.value)}
                  />
                  <p className="mt-1 text-xs text-muted-foreground">{t("Vertex AI region")}</p>
                </div>
              </div>
            )}

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

            <div>
                <Label>{t("API Key")} *</Label>
              <Input
                type="password"
                required
                placeholder={t("sk-...")}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="mt-1 text-xxs text-muted-foreground">
                {t("Required for request. A successful connection test is mandatory before submitting.")}
              </p>
            </div>

            <div>
              <Label>{t("Environment")} *</Label>
              <div className="mt-2 flex gap-2">
                {[
                  { value: "uat", label: t("UAT") },
                  { value: "prod", label: t("PROD") },
                  { value: "both", label: t("UAT + PROD") },
                ].map((env) => (
                  <button
                    key={env.value}
                    type="button"
                    onClick={() => setEnvironmentSelection(env.value as "uat" | "prod" | "both")}
                    className={`rounded-md border px-3 py-2 text-sm ${
                      environmentSelection === env.value
                        ? "border-[var(--button-primary)] bg-[var(--button-primary)] text-[var(--button-primary-foreground)]"
                        : "border-input bg-background"
                    }`}
                  >
                    {env.label}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xxs text-muted-foreground">
                {t("Selecting UAT + PROD submits a single approval for both environments.")}
              </p>
            </div>
          </fieldset>

          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Availability")}
            </legend>
            <p className="text-xs text-muted-foreground">{t("Choose where this model should appear")}</p>
            <div className="flex flex-col gap-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showInOrchestrator}
                  onChange={(e) => { if (!e.target.checked && !showInAgent) return; setShowInOrchestrator(e.target.checked); }}
                  className="h-4 w-4 rounded border-border"
                />
                {t("Orchestrator Chat")}
                <span className="text-xs text-muted-foreground">({t("direct model chat")})</span>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showInAgent}
                  onChange={(e) => { if (!e.target.checked && !showInOrchestrator) return; setShowInAgent(e.target.checked); }}
                  className="h-4 w-4 rounded border-border"
                />
                {t("Agent Canvas")}
                <span className="text-xs text-muted-foreground">({t("for building agents")})</span>
              </label>
            </div>
          </fieldset>

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
                      step="0.01"
                      min="0"
                      max="2"
                      placeholder={t("Optional")}
                      value={temperature}
                      onChange={(e) =>
                        setTemperature(e.target.value ? Number(e.target.value) : "")
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

          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            {t("Tenancy")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Visibility Scope")} *</Label>
                <select
                  value={visibilityScope}
                  onChange={(e) =>
                    setVisibilityScope(
                      e.target.value as "private" | "department" | "organization",
                    )
                  }
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="private">{t("private")}</option>
                  <option value="department">{t("department")}</option>
                  <option value="organization">{t("organization")}</option>
                </select>
              </div>

              {visibilityScope === "department" ? (
                <div>
                  <Label>{canMultiDept ? `${t("Departments")} *` : `${t("Department")} *`}</Label>
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
                      disabled={
                        normalizedRole === "developer" ||
                        normalizedRole === "department_admin"
                      }
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
                <div className="flex items-end text-xs text-muted-foreground">
                  {t("Organization is derived automatically from your tenancy scope.")}
                </div>
              )}
            </div>
          </fieldset>

          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {t("Request Details")}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>{t("Charge Code")} *</Label>
                <Input
                  required
                  placeholder={t("e.g., CC-1042")}
                  value={chargeCode}
                  onChange={(e) => setChargeCode(e.target.value)}
                />
              </div>
              <div>
                <Label>{t("Project Name")} *</Label>
                <Input
                  required
                  placeholder={t("e.g., Customer Support Revamp")}
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                />
              </div>
            </div>

            <div>
              <Label>{t("Reason")} *</Label>
              <Textarea
                required
                rows={4}
                placeholder={t("Tell admins why this model is needed and expected use-case.")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
          </fieldset>
        </form>

        <div className="flex-shrink-0 border-t p-6">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={handleTestConnection}
              disabled={testMutation.isPending || !modelName || !apiKey}
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
              onClick={handleSubmit}
              disabled={isSubmitting || createMutation.isPending}
            >
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isEmbedding ? t("Submit Embedding Request") : t("Submit Model Request")}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {isDirectAddPath
              ? t("This will be auto-approved.")
              : t("This will create an approval request based on environment and visibility.")}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
