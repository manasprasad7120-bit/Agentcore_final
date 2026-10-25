import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import IconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useGetCostLimits,
  useCreateCostLimit,
  useUpdateCostLimit,
  useDeleteCostLimit,
} from "@/controllers/API/queries/cost-limits";
import {
  useGetOrganizations,
  useGetDepartments,
} from "@/controllers/API/queries/auth";
import type {
  CostLimitResponse,
  CostLimitCreatePayload,
  CostLimitUpdatePayload,
} from "@/controllers/API/queries/cost-limits/types";
import type {
  OrganizationListItem,
  DepartmentListItem,
} from "@/controllers/API/queries/auth";
import ConfirmationModal from "@/modals/confirmationModal";
import useAlertStore from "@/stores/alertStore";
import { AuthContext } from "@/contexts/authContext";

export default function CostLimitsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { userData, role } = useContext(AuthContext);
  const normalizedRole = (role ?? "").toLowerCase();

  const [limits, setLimits] = useState<CostLimitResponse[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [editingLimit, setEditingLimit] = useState<CostLimitResponse | null>(null);
  const [organizations, setOrganizations] = useState<OrganizationListItem[]>([]);
  const [departments, setDepartments] = useState<DepartmentListItem[]>([]);

  // Form state
  const [formScopeType, setFormScopeType] = useState<"organization" | "department">("organization");
  const [formOrgId, setFormOrgId] = useState("");
  const [formDeptId, setFormDeptId] = useState("");
  const [formLimitAmount, setFormLimitAmount] = useState("");
  const [formWarningPct, setFormWarningPct] = useState("80");
  const [formPeriodStartDay, setFormPeriodStartDay] = useState("1");
  const [formIsEnabled, setFormIsEnabled] = useState(true);

  const { mutate: mutateGetLimits } = useGetCostLimits();
  const { mutate: mutateCreateLimit } = useCreateCostLimit();
  const { mutate: mutateUpdateLimit } = useUpdateCostLimit();
  const { mutate: mutateDeleteLimit } = useDeleteCostLimit();
  const { mutate: mutateGetOrganizations } = useGetOrganizations();
  const { mutate: mutateGetDepartments } = useGetDepartments();

  function fetchLimits() {
    mutateGetLimits(undefined, {
      onSuccess: (data) => setLimits(Array.isArray(data) ? data : []),
    });
  }

  useEffect(() => {
    fetchLimits();
    mutateGetOrganizations(undefined, {
      onSuccess: (items) => setOrganizations(Array.isArray(items) ? items : []),
    });
    mutateGetDepartments(undefined, {
      onSuccess: (items) => setDepartments(Array.isArray(items) ? items : []),
    });
  }, []);

  function resetForm() {
    setFormScopeType(normalizedRole === "department_admin" ? "department" : "organization");
    setFormOrgId("");
    setFormDeptId("");
    setFormLimitAmount("");
    setFormWarningPct("80");
    setFormPeriodStartDay("1");
    setFormIsEnabled(true);
    setEditingLimit(null);
  }

  function openCreateModal() {
    resetForm();
    setShowModal(true);
  }

  function openEditModal(limit: CostLimitResponse) {
    setEditingLimit(limit);
    setFormScopeType(limit.scope_type);
    setFormOrgId(limit.org_id);
    setFormDeptId(limit.dept_id || "");
    setFormLimitAmount(String(limit.limit_amount_usd));
    setFormWarningPct(String(limit.warning_threshold_pct));
    setFormPeriodStartDay(String(limit.period_start_day));
    setFormIsEnabled(limit.is_enabled);
    setShowModal(true);
  }

  function handleSubmit() {
    const amount = parseFloat(formLimitAmount);
    if (!amount || amount <= 0) {
      setErrorData({ title: t("Invalid limit amount"), list: [t("Please enter a valid positive number.")] });
      return;
    }

    // For dept_admin, resolve org_id from their first org membership (they don't see org dropdown)
    let resolvedOrgId = formOrgId;
    if (normalizedRole === "department_admin" && !resolvedOrgId) {
      // Use the org from user's department info or first available org
      const userOrgId = (userData as any)?.organization_id;
      if (userOrgId) {
        resolvedOrgId = userOrgId;
      } else if (organizations.length > 0) {
        resolvedOrgId = organizations[0].id;
      }
    }

    if (!resolvedOrgId && normalizedRole !== "department_admin") {
      setErrorData({ title: t("Organization required"), list: [t("Please select an organization.")] });
      return;
    }
    if (formScopeType === "department" && !formDeptId) {
      setErrorData({ title: t("Department required"), list: [t("Please select a department.")] });
      return;
    }

    if (editingLimit) {
      const payload: CostLimitUpdatePayload = {
        limit_amount_usd: amount,
        warning_threshold_pct: parseInt(formWarningPct) || 80,
        period_start_day: parseInt(formPeriodStartDay) || 1,
        is_enabled: formIsEnabled,
      };
      mutateUpdateLimit(
        { limit_id: editingLimit.id, payload },
        {
          onSuccess: () => {
            setSuccessData({ title: t("Cost limit updated successfully.") });
            setShowModal(false);
            resetForm();
            fetchLimits();
            queryClient.invalidateQueries({ queryKey: ["costLimitStatus"] });
          },
          onError: (error: any) => {
            setErrorData({
              title: t("Failed to update cost limit"),
              list: [error?.response?.data?.detail || t("Unknown error")],
            });
          },
        },
      );
    } else {
      const payload: CostLimitCreatePayload = {
        scope_type: formScopeType,
        org_id: resolvedOrgId,
        dept_id: formScopeType === "department" ? formDeptId : undefined,
        limit_amount_usd: amount,
        warning_threshold_pct: parseInt(formWarningPct) || 80,
        period_start_day: parseInt(formPeriodStartDay) || 1,
      };
      mutateCreateLimit(payload, {
        onSuccess: () => {
          setSuccessData({ title: t("Cost limit created successfully.") });
          setShowModal(false);
          resetForm();
          fetchLimits();
          queryClient.invalidateQueries({ queryKey: ["costLimitStatus"] });
        },
        onError: (error: any) => {
          setErrorData({
            title: t("Failed to create cost limit"),
            list: [error?.response?.data?.detail || t("Unknown error")],
          });
        },
      });
    }
  }

  function handleDelete(limit: CostLimitResponse) {
    mutateDeleteLimit(
      { limit_id: limit.id },
      {
        onSuccess: () => {
          setSuccessData({ title: t("Cost limit deleted.") });
          fetchLimits();
          queryClient.invalidateQueries({ queryKey: ["costLimitStatus"] });
        },
        onError: (error: any) => {
          setErrorData({
            title: t("Failed to delete cost limit"),
            list: [error?.response?.data?.detail || t("Unknown error")],
          });
        },
      },
    );
  }

  function getStatusBadge(limit: CostLimitResponse) {
    const cost = limit.current_period_cost_usd ?? 0;
    const pct = limit.limit_amount_usd > 0 ? (cost / limit.limit_amount_usd) * 100 : 0;

    if (pct >= 100) {
      return (
        <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
          {t("Exceeded")}
        </span>
      );
    }
    if (pct >= limit.warning_threshold_pct) {
      return (
        <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
          {t("Warning")}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
        {t("Normal")}
      </span>
    );
  }

  function getProgressBar(limit: CostLimitResponse) {
    const cost = limit.current_period_cost_usd ?? 0;
    const pct = limit.limit_amount_usd > 0 ? Math.min((cost / limit.limit_amount_usd) * 100, 100) : 0;

    let bgColor = "bg-green-500";
    if (pct >= 100) bgColor = "bg-red-500";
    else if (pct >= limit.warning_threshold_pct) bgColor = "bg-amber-500";

    return (
      <div className="flex items-center gap-2">
        <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full ${bgColor} transition-all`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xs text-muted-foreground">{pct.toFixed(1)}%</span>
      </div>
    );
  }

  function formatCurrency(val: number) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
  }

  return (
    <>
      {userData && (
        <div className="admin-page-panel flex h-full flex-col pb-8">
          <div className="main-page-nav-arrangement">
            <span className="main-page-nav-title">
              <IconComponent name="DollarSign" className="w-6" />
              {t("Cost Limits")}
            </span>
          </div>
          <span className="admin-page-description-text">
            {t("Set cost thresholds for organizations and departments. Admins will be notified when costs approach or exceed the configured limits.")}
          </span>

          <div className="flex w-full items-center justify-end px-4">
            <Button variant="primary" onClick={openCreateModal}>
              <IconComponent name="Plus" className="mr-2 h-4 w-4" />
              {t("Set Cost Limit")}
            </Button>
          </div>

          <div className="m-4 h-fit overflow-x-hidden overflow-y-scroll rounded-md border-2 bg-background custom-scroll">
            <Table className="table-fixed outline-1">
              <TableHeader className="table-fixed bg-muted outline-1">
                <TableRow>
                  <TableHead className="h-10">{t("Scope")}</TableHead>
                  <TableHead className="h-10">{t("Name")}</TableHead>
                  <TableHead className="h-10">{t("Limit (USD)")}</TableHead>
                  <TableHead className="h-10">{t("Current Cost")}</TableHead>
                  <TableHead className="h-10">{t("Progress")}</TableHead>
                  <TableHead className="h-10">{t("Warning At")}</TableHead>
                  <TableHead className="h-10">{t("Status")}</TableHead>
                  <TableHead className="h-10">{t("Enabled")}</TableHead>
                  <TableHead className="h-10 w-[100px] text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {limits.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                      {t("No cost limits configured. Click 'Set Cost Limit' to create one.")}
                    </TableCell>
                  </TableRow>
                ) : (
                  limits.map((limit) => (
                    <TableRow key={limit.id}>
                      <TableCell className="truncate py-2">
                        <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                          {limit.scope_type === "organization" ? t("Org") : t("Dept")}
                        </span>
                      </TableCell>
                      <TableCell className="truncate py-2">
                        {limit.scope_type === "organization"
                          ? limit.org_name || "-"
                          : limit.dept_name || "-"}
                      </TableCell>
                      <TableCell className="truncate py-2 font-medium">
                        {formatCurrency(limit.limit_amount_usd)}
                      </TableCell>
                      <TableCell className="truncate py-2">
                        {formatCurrency(limit.current_period_cost_usd ?? 0)}
                      </TableCell>
                      <TableCell className="py-2">
                        {getProgressBar(limit)}
                      </TableCell>
                      <TableCell className="truncate py-2">
                        {limit.warning_threshold_pct}%
                      </TableCell>
                      <TableCell className="py-2">
                        {getStatusBadge(limit)}
                      </TableCell>
                      <TableCell className="truncate py-2">
                        {limit.is_enabled ? (
                          <span className="text-green-600">{t("Yes")}</span>
                        ) : (
                          <span className="text-muted-foreground">{t("No")}</span>
                        )}
                      </TableCell>
                      <TableCell className="flex w-[100px] py-2 text-right">
                        <div className="flex gap-1">
                          <button
                            onClick={() => openEditModal(limit)}
                            className="rounded p-1 hover:bg-muted"
                          >
                            <IconComponent name="Pencil" className="h-4 w-4" />
                          </button>
                          <ConfirmationModal
                            size="x-small"
                            title={t("Delete")}
                            titleHeader={t("Delete Cost Limit")}
                            modalContentTitle={t("Attention!")}
                            cancelText={t("Cancel")}
                            confirmationText={t("Delete")}
                            icon="Trash2"
                            data={limit}
                            index={0}
                            onConfirm={() => handleDelete(limit)}
                          >
                            <ConfirmationModal.Content>
                              <span>
                                {t("Are you sure you want to delete this cost limit? This action cannot be undone.")}
                              </span>
                            </ConfirmationModal.Content>
                            <ConfirmationModal.Trigger>
                              <button className="rounded p-1 hover:bg-muted">
                                <IconComponent name="Trash2" className="h-4 w-4 text-destructive" />
                              </button>
                            </ConfirmationModal.Trigger>
                          </ConfirmationModal>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* Create / Edit Modal */}
      {showModal && (
        <>
          <div
            className="fixed inset-0 z-[60] bg-black/40 transition-opacity"
            onClick={() => { setShowModal(false); resetForm(); }}
          />
          <div className="fixed inset-x-0 top-0 z-[70] flex h-full w-full items-start justify-center p-4">
            <div className="mt-20 flex w-full max-w-lg flex-col overflow-hidden rounded-2xl border bg-background shadow-xl">
              <div className="flex items-center justify-between border-b px-5 py-4">
                <h2 className="text-lg font-semibold">
                  {editingLimit ? t("Edit Cost Limit") : t("Set Cost Limit")}
                </h2>
                <button
                  onClick={() => { setShowModal(false); resetForm(); }}
                  className="rounded-md p-1 text-muted-foreground hover:text-foreground"
                >
                  <IconComponent name="X" className="w-5" />
                </button>
              </div>

              <div className="space-y-4 overflow-auto p-5">
                {/* Scope Type — only root can choose, others are locked */}
                {!editingLimit && normalizedRole === "root" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Scope")}</label>
                    <div className="flex gap-4">
                      <label className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="scopeType"
                          value="organization"
                          checked={formScopeType === "organization"}
                          onChange={() => setFormScopeType("organization")}
                          className="accent-primary"
                        />
                        <span className="text-sm">{t("Organization")}</span>
                      </label>
                      <label className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="scopeType"
                          value="department"
                          checked={formScopeType === "department"}
                          onChange={() => setFormScopeType("department")}
                          className="accent-primary"
                        />
                        <span className="text-sm">{t("Department")}</span>
                      </label>
                    </div>
                  </div>
                )}

                {/* Scope info for non-root users */}
                {!editingLimit && normalizedRole === "super_admin" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Scope")}</label>
                    <p className="text-sm text-muted-foreground">{t("Organization Level")}</p>
                  </div>
                )}
                {!editingLimit && normalizedRole === "department_admin" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Scope")}</label>
                    <p className="text-sm text-muted-foreground">{t("Department Level")}</p>
                  </div>
                )}

                {/* Organization — root picks any, super_admin picks their org */}
                {!editingLimit && (normalizedRole === "root" || normalizedRole === "super_admin") && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Organization")}</label>
                    <select
                      value={formOrgId}
                      onChange={(e) => setFormOrgId(e.target.value)}
                      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="">{t("Select Organization")}</option>
                      {organizations.map((org) => (
                        <option key={org.id} value={org.id}>{org.name}</option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Department — only for root when scope=department, or dept_admin picks their dept */}
                {!editingLimit && normalizedRole === "root" && formScopeType === "department" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Department")}</label>
                    <select
                      value={formDeptId}
                      onChange={(e) => setFormDeptId(e.target.value)}
                      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="">{t("Select Department")}</option>
                      {departments.map((dept) => (
                        <option key={dept.id} value={dept.id}>{dept.name}</option>
                      ))}
                    </select>
                  </div>
                )}
                {!editingLimit && normalizedRole === "department_admin" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Department")}</label>
                    <select
                      value={formDeptId}
                      onChange={(e) => setFormDeptId(e.target.value)}
                      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="">{t("Select Department")}</option>
                      {departments.map((dept) => (
                        <option key={dept.id} value={dept.id}>{dept.name}</option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Limit Amount */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t("Cost Limit (USD)")}</label>
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={formLimitAmount}
                    onChange={(e) => setFormLimitAmount(e.target.value)}
                    placeholder={t("e.g. 10000")}
                  />
                </div>

                {/* Warning Threshold */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">
                    {t("Warning Threshold (%)")}
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min="1"
                      max="100"
                      value={formWarningPct}
                      onChange={(e) => setFormWarningPct(e.target.value)}
                      className="flex-1"
                    />
                    <span className="w-12 text-center text-sm font-medium">
                      {formWarningPct}%
                    </span>
                  </div>
                </div>

                {/* Period Start Day */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t("Billing Period Start Day")}</label>
                  <Input
                    type="number"
                    min="1"
                    max="28"
                    value={formPeriodStartDay}
                    onChange={(e) => setFormPeriodStartDay(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("Day of the month when the billing period starts (1-28).")}
                  </p>
                </div>

                {/* Enabled toggle (edit only) */}
                {editingLimit && (
                  <div className="flex items-center gap-3">
                    <label className="text-sm font-medium">{t("Enabled")}</label>
                    <button
                      type="button"
                      onClick={() => setFormIsEnabled(!formIsEnabled)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        formIsEnabled ? "bg-primary" : "bg-muted"
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          formIsEnabled ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-end gap-3 border-t px-5 py-4">
                <Button
                  variant="outline"
                  onClick={() => { setShowModal(false); resetForm(); }}
                >
                  {t("Cancel")}
                </Button>
                <Button variant="primary" onClick={handleSubmit}>
                  {editingLimit ? t("Update") : t("Create")}
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
