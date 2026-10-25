import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { ForwardedIconComponent } from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import InputListComponent from "@/components/core/parameterRenderComponent/components/inputListComponent";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { MAX_MCP_SERVER_NAME_LENGTH } from "@/constants/constants";
import { AuthContext } from "@/contexts/authContext";
import useAlertStore from "@/stores/alertStore";
import { api } from "@/controllers/API/api";
import { useNameAvailability } from "@/controllers/API/queries/common/use-name-availability";
import { useAddMCPServer } from "@/controllers/API/queries/mcp/use-add-mcp-server";
import { usePatchMCPServer } from "@/controllers/API/queries/mcp/use-patch-mcp-server";
import { useRequestMCPServer } from "@/controllers/API/queries/mcp/use-request-mcp-server";
import { useTestMCPConnection } from "@/controllers/API/queries/mcp/use-test-mcp-connection";
import { useAnalyzeMCPRisk } from "@/controllers/API/queries/mcp/use-analyze-mcp-risk";
import RiskAssessmentPanel from "@/components/RiskAssessmentPanel";
import HighRiskConfirmDialog from "@/components/HighRiskConfirmDialog";
import BaseModal from "@/modals/baseModal";
import IOKeyPairInput from "@/modals/IOModal/components/IOFieldView/components/key-pair-input";
import type {
  McpRegistryType,
  McpRegistryCreateRequest,
  McpRiskAnalysisResponse,
  McpRiskAnalyzeRequest,
  McpRiskFinding,
  McpTestConnectionResponse,
} from "@/types/mcp";
import type { MCPServerType } from "@/types/mcp";
import { extractMcpServersFromJson } from "@/utils/mcpUtils";
import { cn } from "@/utils/utils";

type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
};

export default function AddMcpServerModal({
  children,
  initialData,
  requestMode = false,
  open: myOpen,
  setOpen: mySetOpen,
  onSuccess,
}: {
  children?: JSX.Element;
  initialData?: McpRegistryType;
  requestMode?: boolean;
  open?: boolean;
  setOpen?: (a: boolean | ((o?: boolean) => boolean)) => void;
  onSuccess?: (server: string) => void;
}): JSX.Element {
  const [open, setOpen] =
    mySetOpen !== undefined && myOpen !== undefined
      ? [myOpen, mySetOpen]
      : useState(false);
  const { role } = useContext(AuthContext);
  const normalizedRole = String(role || "").toLowerCase();
  const canMultiDept = normalizedRole === "super_admin" || normalizedRole === "root";
  const isEditMode = !!initialData;

  const [type, setType] = useState(
    initialData ? (initialData.mode === "stdio" ? "STDIO" : "SSE") : "SSE",
  );
  const [deploymentEnvSelection, setDeploymentEnvSelection] = useState<"uat" | "prod" | "both">(
    (() => {
      const normalized = String(initialData?.deployment_env || "DEV").toLowerCase();
      if (normalized === "uat" || normalized === "prod") return normalized as "uat" | "prod";
      return "uat";
    })(),
  );
  const [error, setError] = useState<string | null>(null);
  const addMutation = useAddMCPServer();
  const patchMutation = usePatchMCPServer();
  const requestMutation = useRequestMCPServer();
  const testMutation = useTestMCPConnection();
  const analyzeRiskMutation = useAnalyzeMCPRisk();
  const [riskAnalysis, setRiskAnalysis] = useState<McpRiskAnalysisResponse | null>(null);
  const [pendingRiskAction, setPendingRiskAction] = useState<
    null | { kind: "test" | "submit"; findings: McpRiskFinding[] }
  >(null);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const isPending =
    addMutation.isPending || patchMutation.isPending || requestMutation.isPending;
  const [testResult, setTestResult] =
    useState<McpTestConnectionResponse | null>(null);
  const [testPayloadKey, setTestPayloadKey] = useState<string | null>(null);

  const [stdioName, setStdioName] = useState(initialData?.server_name || "");
  const [stdioCommand, setStdioCommand] = useState(initialData?.command || "");
  const [stdioArgs, setStdioArgs] = useState<string[]>(initialData?.args || [""]);
  const [stdioEnv, setStdioEnv] = useState<any>([]);
  const [stdioDescription, setStdioDescription] = useState(initialData?.description || "");

  const [sseName, setSseName] = useState(initialData?.server_name || "");
  const [sseUrl, setSseUrl] = useState(initialData?.url || "");
  const [sseEnv, setSseEnv] = useState<any>([]);
  const [sseHeaders, setSseHeaders] = useState<any>([]);
  const [sseDescription, setSseDescription] = useState(initialData?.description || "");
  const activeNameInput = type === "STDIO" ? stdioName : type === "SSE" ? sseName : "";
  const normalizedActiveName = activeNameInput.trim().slice(0, MAX_MCP_SERVER_NAME_LENGTH);
  const nameAvailability = useNameAvailability({
    entity: "mcp",
    name: normalizedActiveName,
    exclude_id: initialData?.id ?? null,
    enabled: open && type !== "JSON" && activeNameInput.trim().length > 0,
  });
  const isNameTaken = nameAvailability.isNameTaken;

  const [jsonInput, setJsonInput] = useState("");
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">(() => {
    if (initialData?.visibility === "public") {
      return initialData?.public_scope === "organization" ? "organization" : "department";
    }
    return "private";
  });
  const [orgId, setOrgId] = useState(initialData?.org_id || "");
  const [deptId, setDeptId] = useState(initialData?.dept_id || "");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>(
    initialData?.public_dept_ids || [],
  );
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });
  const formScrollRef = useRef<HTMLDivElement | null>(null);
  const tenancySectionRef = useRef<HTMLDivElement | null>(null);

  const departmentsForSelectedOrg = useMemo(
    () =>
      visibilityOptions.departments.filter((d) => !orgId || d.org_id === orgId),
    [visibilityOptions.departments, orgId],
  );
  const selectedDeptLabel = useMemo(() => {
    if (publicDeptIds.length === 0) return "Select departments";
    const names = departmentsForSelectedOrg
      .filter((dept) => publicDeptIds.includes(dept.id))
      .map((dept) => dept.name);
    if (names.length === 0) return "Select departments";
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [departmentsForSelectedOrg, publicDeptIds]);

  function parseEnvList(envList: any): Record<string, string> {
    const env: Record<string, string> = {};
    if (Array.isArray(envList)) {
      envList.forEach((obj) => {
        const key = Object.keys(obj)[0];
        if (key && key.trim() !== "") env[key] = obj[key];
      });
    }
    return env;
  }

  function buildTestPayload() {
    if (type === "STDIO") {
      return {
        mode: "stdio",
        command: stdioCommand,
        args: stdioArgs.filter((a) => a.trim() !== ""),
        env_vars: parseEnvList(stdioEnv),
      };
    }
    if (type === "SSE") {
      return {
        mode: "sse",
        url: sseUrl,
        env_vars: parseEnvList(sseEnv),
        headers: parseEnvList(sseHeaders),
      };
    }
    return null;
  }

  function buildTestKey(payload: ReturnType<typeof buildTestPayload>) {
    if (!payload) return null;
    return JSON.stringify(payload);
  }

  function formatServerName(value: string) {
    return value.trim().slice(0, MAX_MCP_SERVER_NAME_LENGTH);
  }

  function buildRiskPayload(): McpRiskAnalyzeRequest | null {
    if (type === "STDIO") {
      if (
        !stdioCommand.trim() &&
        stdioArgs.every((a) => !a.trim()) &&
        !stdioEnv.length
      )
        return null;
      return {
        mode: "stdio",
        command: stdioCommand,
        args: stdioArgs.filter((a) => a.trim() !== ""),
        env_vars: parseEnvList(stdioEnv),
      };
    }
    if (type === "SSE") {
      if (!sseUrl.trim() && !sseHeaders.length && !sseEnv.length) return null;
      return {
        mode: "sse",
        url: sseUrl,
        env_vars: parseEnvList(sseEnv),
        headers: parseEnvList(sseHeaders),
      };
    }
    return null;
  }

  function getHighFindings(): McpRiskFinding[] {
    if (!riskAnalysis) return [];
    return riskAnalysis.findings.filter((f) => f.severity === "high");
  }

  function buildTenancyPayload() {
    const isPublic = visibilityScope !== "private";
    const resolvedPrivateDeptId = canMultiDept
      ? deptId || publicDeptIds[0] || undefined
      : deptId || undefined;
    return {
      visibility: isPublic ? "public" : "private",
      public_scope: isPublic ? visibilityScope : null,
      org_id: orgId || undefined,
      dept_id:
        visibilityScope === "department"
          ? (canMultiDept ? undefined : deptId || undefined)
          : visibilityScope === "private"
            ? resolvedPrivateDeptId
            : undefined,
      public_dept_ids:
        visibilityScope === "department"
          ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : [])
          : [],
    };
  }

  useEffect(() => {
    if (!open || type === "JSON") {
      setRiskAnalysis(null);
      return;
    }
    const payload = buildRiskPayload();
    if (!payload) {
      setRiskAnalysis(null);
      return;
    }
    const handle = setTimeout(() => {
      analyzeRiskMutation
        .mutateAsync(payload)
        .then((res) => setRiskAnalysis(res))
        .catch(() => setRiskAnalysis(null));
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    open,
    type,
    stdioCommand,
    JSON.stringify(stdioArgs),
    JSON.stringify(stdioEnv),
    sseUrl,
    JSON.stringify(sseEnv),
    JSON.stringify(sseHeaders),
  ]);

  async function testConnection() {
    const highs = getHighFindings();
    if (highs.length > 0 && !pendingRiskAction) {
      setPendingRiskAction({ kind: "test", findings: highs });
      return;
    }
    await testConnectionInner();
  }

  async function testConnectionInner() {
    setTestResult(null);
    setError(null);
    try {
      if (type === "STDIO") {
        if (!stdioCommand.trim()) return setError("Command is required to test connection.");
        const payload = buildTestPayload();
        const result = await testMutation.mutateAsync(payload!);
        setTestResult(result);
        setTestPayloadKey(buildTestKey(payload));
      } else if (type === "SSE") {
        if (!sseUrl.trim()) return setError("URL is required to test connection.");
        const payload = buildTestPayload();
        const result = await testMutation.mutateAsync(payload!);
        setTestResult(result);
        setTestPayloadKey(buildTestKey(payload));
      }
    } catch (err: any) {
      const message = err?.message || "Connection failed.";
      setTestResult({ success: false, message });
      setTestPayloadKey(buildTestKey(buildTestPayload()));
      setErrorData({ title: "Connection test failed", list: [message] });
    }
  }

  async function submitForm() {
    const highs = getHighFindings();
    if (highs.length > 0 && !pendingRiskAction && type !== "JSON") {
      setPendingRiskAction({ kind: "submit", findings: highs });
      return;
    }
    await submitFormInner();
  }

  async function submitFormInner() {
    setError(null);
    if (type !== "JSON" && isNameTaken) {
      setError(nameAvailability.reason || "Name is already taken.");
      return;
    }
    const tenancyPayload = buildTenancyPayload();
    const desiredEnvs =
      deploymentEnvSelection === "both" ? ["uat", "prod"] : [deploymentEnvSelection];
    const primaryEnv = desiredEnvs[0] ?? "uat";
    const requiresTest = !isEditMode && !requestMode && type !== "JSON";

    if (type === "STDIO") {
      if (!stdioName.trim() || !stdioCommand.trim()) return setError("Name and command are required.");
      const serverName = formatServerName(stdioName);
      try {
        if (requiresTest) {
          const payload = buildTestPayload();
          const key = buildTestKey(payload);
          let result = testResult && testPayloadKey === key ? testResult : null;
          let autoTestRan = false;
          if (!result) {
            result = await testMutation.mutateAsync(payload!);
            setTestResult(result);
            setTestPayloadKey(key);
            autoTestRan = true;
          }
          if (!result.success) {
            const msg = result.message || "Connection test failed.";
            setError(msg);
            setErrorData({ title: "Connection test failed", list: [msg] });
            return;
          }
          if (autoTestRan) {
            setSuccessData({ title: result.message || "Connection successful" });
          }
        }
        const payload: McpRegistryCreateRequest = {
          server_name: serverName,
          description: stdioDescription || null,
          mode: "stdio",
          deployment_env: primaryEnv,
          environments: desiredEnvs,
          command: stdioCommand,
          args: stdioArgs.filter((a) => a.trim() !== ""),
          env_vars: parseEnvList(stdioEnv),
          ...tenancyPayload,
        };
        if (isEditMode && initialData) {
          await patchMutation.mutateAsync({ id: initialData.id, data: payload });
        } else if (requestMode) {
          await requestMutation.mutateAsync(payload);
        } else {
          await addMutation.mutateAsync(payload);
        }
        setSuccessData({
          title: isEditMode
            ? "MCP server updated"
            : requestMode
              ? "MCP server request submitted"
              : "MCP server registered",
          list: requestMode
            ? ["Your request has been sent for approval."]
            : ["If approval is required, you'll see it in Review & Approval."],
        });
        onSuccess?.(serverName);
        setOpen(false);
        resetForm();
      } catch (err: any) {
        const message = err?.message || "Failed to save MCP server.";
        setError(message);
        setErrorData({ title: "MCP server save failed", list: [message] });
      }
      return;
    }

    if (type === "SSE") {
      if (!sseName.trim() || !sseUrl.trim()) return setError("Name and URL are required.");
      const serverName = formatServerName(sseName);
      try {
        if (requiresTest) {
          const payload = buildTestPayload();
          const key = buildTestKey(payload);
          let result = testResult && testPayloadKey === key ? testResult : null;
          let autoTestRan = false;
          if (!result) {
            result = await testMutation.mutateAsync(payload!);
            setTestResult(result);
            setTestPayloadKey(key);
            autoTestRan = true;
          }
          if (!result.success) {
            const msg = result.message || "Connection test failed.";
            setError(msg);
            setErrorData({ title: "Connection test failed", list: [msg] });
            return;
          }
          if (autoTestRan) {
            setSuccessData({ title: result.message || "Connection successful" });
          }
        }
        const payload: McpRegistryCreateRequest = {
          server_name: serverName,
          description: sseDescription || null,
          mode: "sse",
          deployment_env: primaryEnv,
          environments: desiredEnvs,
          url: sseUrl,
          env_vars: parseEnvList(sseEnv),
          headers: parseEnvList(sseHeaders),
          ...tenancyPayload,
        };
        if (isEditMode && initialData) {
          await patchMutation.mutateAsync({ id: initialData.id, data: payload });
        } else if (requestMode) {
          await requestMutation.mutateAsync(payload);
        } else {
          await addMutation.mutateAsync(payload);
        }
        setSuccessData({
          title: isEditMode
            ? "MCP server updated"
            : requestMode
              ? "MCP server request submitted"
              : "MCP server registered",
          list: requestMode
            ? ["Your request has been sent for approval."]
            : ["If approval is required, you'll see it in Review & Approval."],
        });
        onSuccess?.(serverName);
        setOpen(false);
        resetForm();
      } catch (err: any) {
        const message = err?.message || "Failed to save MCP server.";
        setError(message);
        setErrorData({ title: "MCP server save failed", list: [message] });
      }
      return;
    }

    if (type === "JSON") {
      if (!jsonInput.trim()) return setError("JSON configuration is required.");
      let servers: MCPServerType[];
      try {
        servers = extractMcpServersFromJson(jsonInput);
      } catch (err: any) {
        return setError(err?.message || "Invalid JSON format.");
      }
      try {
        for (const srv of servers) {
          const serverName = formatServerName(srv.name);
          const mode: "sse" | "stdio" = srv.command ? "stdio" : "sse";
          if (!requestMode) {
            const testPayload =
              mode === "stdio"
                ? {
                    mode,
                    command: srv.command,
                    args: srv.args?.filter((a) => a.trim() !== ""),
                    env_vars: srv.env ?? undefined,
                  }
                : {
                    mode,
                    url: srv.url,
                    env_vars: srv.env ?? undefined,
                    headers: srv.headers ?? undefined,
                  };
            const testResult = await testMutation.mutateAsync(testPayload as any);
            if (!testResult.success) {
              const msg = testResult.message || "Connection test failed.";
              setError(msg);
              setErrorData({ title: "Connection test failed", list: [msg] });
              return;
            }
          }
          const createReq: McpRegistryCreateRequest = {
            server_name: serverName,
            mode,
            deployment_env: primaryEnv,
            environments: desiredEnvs,
            ...(mode === "stdio" && {
              command: srv.command,
              args: srv.args?.filter((a) => a.trim() !== ""),
            }),
            ...(mode === "sse" && {
              url: srv.url,
              headers: srv.headers && Object.keys(srv.headers).length > 0 ? srv.headers : undefined,
            }),
            env_vars: srv.env && Object.keys(srv.env).length > 0 ? srv.env : undefined,
            ...tenancyPayload,
          };
          if (requestMode) {
            await requestMutation.mutateAsync(createReq);
          } else {
            await addMutation.mutateAsync(createReq);
          }
        }
        setSuccessData({
          title: requestMode ? "MCP server request submitted" : "MCP server(s) registered",
          list: requestMode
            ? ["Your request has been sent for approval."]
            : ["If approval is required, you'll see it in Review & Approval."],
        });
        onSuccess?.(servers[0]?.name || "");
        setOpen(false);
        resetForm();
      } catch (err: any) {
        const message = err?.message || "Failed to import MCP server(s).";
        setError(message);
        setErrorData({ title: "MCP server import failed", list: [message] });
      }
    }
  }

  function resetForm() {
    setStdioName("");
    setStdioCommand("");
    setStdioArgs([""]);
    setStdioEnv([]);
    setStdioDescription("");
    setSseName("");
    setSseUrl("");
    setSseEnv([]);
    setSseHeaders([]);
    setSseDescription("");
    setJsonInput("");
    setDeploymentEnvSelection("uat");
    setVisibilityScope("private");
    setOrgId("");
    setDeptId("");
    setPublicDeptIds([]);
    setError(null);
    setTestResult(null);
    setTestPayloadKey(null);
  }

  useEffect(() => {
    if (!open) return;
    setType(initialData ? (initialData.mode === "stdio" ? "STDIO" : "SSE") : "SSE");
    setError(null);
    setStdioName(initialData?.server_name || "");
    setStdioCommand(initialData?.command || "");
    setStdioArgs(initialData?.args || [""]);
    setStdioEnv([]);
    setStdioDescription(initialData?.description || "");
    setSseName(initialData?.server_name || "");
    setSseUrl(initialData?.url || "");
    setSseEnv([]);
    setSseHeaders([]);
    setSseDescription(initialData?.description || "");
    {
      const envs = (initialData?.environments || []).map((env) => String(env).toLowerCase());
      if (envs.includes("uat") && envs.includes("prod")) {
        setDeploymentEnvSelection("both");
      } else {
        const normalized = String(initialData?.deployment_env || "UAT").toLowerCase();
        setDeploymentEnvSelection(
          normalized === "uat" || normalized === "prod" ? (normalized as "uat" | "prod") : "uat",
        );
      }
    }
    setVisibilityScope(
      initialData?.visibility === "public"
        ? (initialData?.public_scope === "organization" ? "organization" : "department")
        : "private",
    );
    setOrgId(initialData?.org_id || "");
    setDeptId(initialData?.dept_id || "");
    setPublicDeptIds(initialData?.public_dept_ids || []);
  }, [open, initialData]);

  useEffect(() => {
    if (!open) return;
    api.get("api/mcp/registry/visibility-options").then((res) => {
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
    if (!open || visibilityScope !== "private" || !canMultiDept) return;
    const fallbackDeptId =
      deptId ||
      publicDeptIds[0] ||
      initialData?.dept_id ||
      initialData?.public_dept_ids?.[0] ||
      departmentsForSelectedOrg[0]?.id ||
      visibilityOptions.departments[0]?.id ||
      "";
    if (fallbackDeptId && deptId !== fallbackDeptId) {
      setDeptId(fallbackDeptId);
    }
    if (!orgId) {
      const fallbackOrgId =
        departmentsForSelectedOrg.find((dept) => dept.id === fallbackDeptId)?.org_id ||
        visibilityOptions.departments.find((dept) => dept.id === fallbackDeptId)?.org_id ||
        visibilityOptions.organizations[0]?.id ||
        "";
      if (fallbackOrgId) setOrgId(fallbackOrgId);
    }
  }, [
    open,
    visibilityScope,
    canMultiDept,
    deptId,
    publicDeptIds,
    orgId,
    initialData,
    departmentsForSelectedOrg,
    visibilityOptions.departments,
    visibilityOptions.organizations,
  ]);

  const handleTypeChange = (val: string) => {
    setType(val);
    setError(null);
    setTestResult(null);
    setTestPayloadKey(null);
  };

  useEffect(() => {
    if (!open || type === "JSON") return;
    const key = buildTestKey(buildTestPayload());
    if (testPayloadKey && key && key !== testPayloadKey) {
      setTestResult(null);
      setTestPayloadKey(null);
    }
  }, [
    open,
    type,
    stdioCommand,
    stdioArgs,
    stdioEnv,
    sseUrl,
    sseEnv,
    sseHeaders,
    testPayloadKey,
  ]);

  useEffect(() => {
    if (!open) return;
    if (visibilityScope === "private") return;

    const scrollContainer = formScrollRef.current;
    const tenancySection = tenancySectionRef.current;
    if (!scrollContainer || !tenancySection) return;

    requestAnimationFrame(() => {
      const containerRect = scrollContainer.getBoundingClientRect();
      const sectionRect = tenancySection.getBoundingClientRect();
      const nextTop =
        tenancySection.offsetTop - scrollContainer.offsetTop - 12;

      if (sectionRect.bottom > containerRect.bottom || sectionRect.top < containerRect.top) {
        scrollContainer.scrollTo({
          top: Math.max(nextTop, 0),
          behavior: "smooth",
        });
      }
    });
  }, [open, visibilityScope, canMultiDept]);

  return (
    <BaseModal open={open} setOpen={setOpen} size="small-update" onSubmit={submitForm} className="!p-0">
      <BaseModal.Trigger>{children}</BaseModal.Trigger>
      <BaseModal.Content className="flex flex-col justify-between overflow-hidden">
        <div className="flex h-full w-full flex-col overflow-hidden">
          <div className="flex flex-col gap-3 p-4 tracking-normal">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ForwardedIconComponent name="Server" className="h-4 w-4 text-primary" aria-hidden="true" />
              {isEditMode ? "Edit MCP Server" : requestMode ? "Request MCP Server" : "Register MCP Server"}
            </div>
          </div>
          <div className="flex h-full w-full flex-col overflow-hidden">
            <div className="flex flex-col gap-4 border-y p-4">
              <div className="flex flex-col gap-2">
                <Label className="!text-mmd">Transport</Label>
                <Select value={type} onValueChange={handleTypeChange} disabled={isEditMode}>
                  <SelectTrigger data-testid="connection-type-select" className="w-full">
                    <SelectValue placeholder="Select transport..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SSE">SSE</SelectItem>
                    <SelectItem value="STDIO">STDIO</SelectItem>
                    {!isEditMode && <SelectItem value="JSON">JSON</SelectItem>}
                  </SelectContent>
                </Select>
              </div>
              {error && (
                <ShadTooltip content={error}>
                  <div className={cn("truncate text-xs font-medium text-red-500")}>{error}</div>
                </ShadTooltip>
              )}
              {type !== "JSON" && activeNameInput.trim().length > 0 && !nameAvailability.isFetching && isNameTaken && (
                <div className="text-xs font-medium text-red-500">
                  {nameAvailability.reason ?? "Name is already taken."}
                </div>
              )}
              <div
                ref={formScrollRef}
                className="flex max-h-[380px] flex-col gap-4 overflow-y-auto"
                id="global-variable-modal-inputs"
              >
                <div className="flex flex-col gap-2">
                  <Label className="!text-mmd">Environment</Label>
                  <div className="flex gap-2">
                    {[
                      { value: "uat", label: "UAT" },
                      { value: "prod", label: "PROD" },
                      { value: "both", label: "UAT + PROD" },
                    ].map((env) => (
                      <button
                        key={env.value}
                        type="button"
                        onClick={() => setDeploymentEnvSelection(env.value as "uat" | "prod" | "both")}
                        className={`rounded-md border px-3 py-2 text-sm font-medium ${
                          deploymentEnvSelection === env.value
                            ? "border-[var(--button-primary)] bg-[var(--button-primary)] text-[var(--button-primary-foreground)]"
                            : "border-input bg-background hover:bg-muted"
                        }`}
                        disabled={isPending}
                      >
                        {env.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-xxs text-muted-foreground">
                    Selecting <strong>UAT + PROD</strong> submits a single approval for both environments.
                  </p>
                </div>
                {type === "STDIO" && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Name <span className="text-red-500">*</span></Label>
                      <Input value={stdioName} onChange={(e) => setStdioName(e.target.value)} placeholder="Server name" data-testid="stdio-name-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Description</Label>
                      <Input value={stdioDescription} onChange={(e) => setStdioDescription(e.target.value)} placeholder="Brief description" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Command<span className="text-red-500">*</span></Label>
                      <Input value={stdioCommand} onChange={(e) => setStdioCommand(e.target.value)} placeholder="Command to run" data-testid="stdio-command-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Arguments</Label>
                      <InputListComponent value={stdioArgs} handleOnNewValue={({ value }) => setStdioArgs(value)} disabled={isPending} placeholder="Add argument" listAddLabel="Add Argument" editNode={false} id="stdio-args" data-testid="stdio-args-input" />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Environment Variables</Label>
                      <IOKeyPairInput value={stdioEnv} onChange={setStdioEnv} duplicateKey={false} isList={true} isInputField={true} testId="stdio-env" />
                    </div>
                  </div>
                )}
                {type === "SSE" && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Name<span className="text-red-500">*</span></Label>
                      <Input value={sseName} onChange={(e) => setSseName(e.target.value)} placeholder="Server name" data-testid="sse-name-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Description</Label>
                      <Input value={sseDescription} onChange={(e) => setSseDescription(e.target.value)} placeholder="Brief description" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Endpoint URL<span className="text-red-500">*</span></Label>
                      <Input value={sseUrl} onChange={(e) => setSseUrl(e.target.value)} placeholder="Server URL" data-testid="sse-url-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Headers</Label>
                      <IOKeyPairInput value={sseHeaders} onChange={setSseHeaders} duplicateKey={false} isList={true} isInputField={true} testId="sse-headers" />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Environment Variables</Label>
                      <IOKeyPairInput value={sseEnv} onChange={setSseEnv} duplicateKey={false} isList={true} isInputField={true} testId="sse-env" />
                    </div>
                  </div>
                )}
                <div ref={tenancySectionRef} className="flex flex-col gap-4 rounded-md border p-3">
                  <Label className="!text-mmd">Tenancy</Label>
                  <div className="flex flex-col gap-2">
                    <Label className="!text-mmd">Visibility Scope</Label>
                    <select
                      value={visibilityScope}
                      onChange={(e) => setVisibilityScope(e.target.value as "private" | "department" | "organization")}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      disabled={isPending}
                    >
                      <option value="private">private</option>
                      <option value="department">department</option>
                      <option value="organization">organization</option>
                    </select>
                  </div>
                  {visibilityScope === "organization" && (
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Organization</Label>
                      <select
                        value={orgId}
                        onChange={(event) => setOrgId(event.target.value)}
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        disabled={isPending || normalizedRole === "developer" || normalizedRole === "department_admin"}
                      >
                        <option value="">Select organization</option>
                        {visibilityOptions.organizations.map((org) => (
                          <option key={org.id} value={org.id}>{org.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {visibilityScope === "department" && (
                    <>
                      {canMultiDept && (
                        <div className="flex flex-col gap-2">
                          <Label className="!text-mmd">Organization</Label>
                          <select
                            value={orgId}
                            onChange={(event) => {
                              setOrgId(event.target.value);
                              setPublicDeptIds([]);
                            }}
                            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                            disabled={isPending}
                          >
                            <option value="">Select organization</option>
                            {visibilityOptions.organizations.map((org) => (
                              <option key={org.id} value={org.id}>{org.name}</option>
                            ))}
                          </select>
                        </div>
                      )}
                      <div className="flex flex-col gap-2">
                        <Label className="!text-mmd">Department{canMultiDept ? "s" : ""}</Label>
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
                            onChange={(event) => setDeptId(event.target.value)}
                            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                            disabled={isPending || normalizedRole === "developer" || normalizedRole === "department_admin"}
                          >
                            <option value="">Select department</option>
                            {departmentsForSelectedOrg.map((dept) => (
                              <option key={dept.id} value={dept.id}>{dept.name}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    </>
                  )}
                </div>
                {type !== "JSON" && (
                  <div className="flex flex-col gap-2">
                    <Label className="!text-mmd">Risk Assessment</Label>
                    <RiskAssessmentPanel
                      analysis={riskAnalysis}
                      isLoading={analyzeRiskMutation.isPending && !riskAnalysis}
                      compact
                      emptyMessage={
                        type === "STDIO"
                          ? "Enter a command to see the risk assessment."
                          : "Enter a URL to see the risk assessment."
                      }
                    />
                  </div>
                )}
                {type === "JSON" && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">MCP JSON Configuration</Label>
                      <p className="text-xs text-muted-foreground">
                        Paste a standard MCP JSON config. Supports <code className="text-xs">{`{ "mcpServers": { ... } }`}</code>, multiple server objects, or a single server object.
                      </p>
                      <Textarea value={jsonInput} onChange={(e) => setJsonInput(e.target.value)} placeholder={'{\n  "mcpServers": {\n    "server-name": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-everything"]\n    }\n  }\n}'} rows={10} className="font-mono text-xs" data-testid="json-config-input" disabled={isPending} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-2 p-4">
          {testResult && (
            <div className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium", testResult.success ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400" : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400")}>
              <ForwardedIconComponent name={testResult.success ? "CheckCircle2" : "XCircle"} className="h-4 w-4 flex-shrink-0" />
              <span className="truncate">{testResult.success ? `Connected - ${testResult.tools_count ?? 0} tool(s) found` : testResult.message}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <div>
              {type !== "JSON" && !requestMode && (
                <Button variant="outline" size="sm" onClick={testConnection} disabled={isPending || testMutation.isPending} loading={testMutation.isPending} data-testid="test-mcp-connection-button">
                  <ForwardedIconComponent name="Plug" className="mr-1.5 h-3.5 w-3.5" />
                  <span className="text-mmd font-normal">Test Connection</span>
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
                <span className="text-mmd font-normal">Cancel</span>
              </Button>
              <Button
                size="sm"
                onClick={submitForm}
                data-testid="add-mcp-server-button"
                loading={isPending}
                disabled={isNameTaken || nameAvailability.isFetching}
              >
                <span className="text-mmd">{isEditMode ? "Save" : requestMode ? "Submit Request" : type === "JSON" ? "Import" : "Register"}</span>
              </Button>
            </div>
          </div>
        </div>
      </BaseModal.Content>
      <HighRiskConfirmDialog
        open={!!pendingRiskAction}
        highFindings={pendingRiskAction?.findings ?? []}
        actionLabel={
          pendingRiskAction?.kind === "test"
            ? "Test Connection"
            : isEditMode
              ? "Save"
              : requestMode
                ? "Submit Request"
                : type === "JSON"
                  ? "Import"
                  : "Register"
        }
        onCancel={() => setPendingRiskAction(null)}
        onConfirm={() => {
          const action = pendingRiskAction;
          setPendingRiskAction(null);
          if (action?.kind === "test") void testConnectionInner();
          else void submitFormInner();
        }}
      />
    </BaseModal>
  );
}
