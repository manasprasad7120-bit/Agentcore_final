import * as Form from "@radix-ui/react-form";
import { useContext, useEffect, useState } from "react";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import IconComponent from "@/components/common/genericIconComponent";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { DateTimePicker } from "../../components/ui/date-time-picker";
import { CONTROL_NEW_USER } from "../../constants/constants";
import { AuthContext } from "../../contexts/authContext";
import {
  useGetAssignableRoles,
  useGetDepartments,
  useGetOrganizations,
} from "../../controllers/API/queries/auth";
import type {
  inputHandlerEventType,
  UserInputType,
  UserManagementType,
} from "../../types/components";
import BaseModal from "../baseModal";

export default function UserManagementModal({
  title,
  titleHeader,
  cancelText,
  confirmationText,
  children,
  icon,
  data,
  index,
  onConfirm,
  asChild,
}: UserManagementType) {
  const [open, setOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [username, setUserName] = useState(data?.username ?? "");
  const [isActive, setIsActive] = useState(data?.is_active ?? false);
  const [selectedRole, setSelectedRole] = useState(
    data?.role ?? "business_user",
  );
  const [availableRoles, setAvailableRoles] = useState<string[]>([]);
  const [expiresAt, setExpiresAt] = useState<string>(data?.expires_at ?? "");
  const [departmentId, setDepartmentId] = useState("");
  const [departments, setDepartments] = useState<Array<{ id: string; name: string; org_id: string }>>([]);
  const [organizations, setOrganizations] = useState<Array<{ id: string; name: string; status?: string | null }>>([]);
  const [departmentName, setDepartmentName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [organizationDescription, setOrganizationDescription] = useState("");
  const [departmentError, setDepartmentError] = useState("");
  const [organizationError, setOrganizationError] = useState("");
  const [usernameError, setUsernameError] = useState("");
  const { mutate: mutateGetAssignableRoles } = useGetAssignableRoles();
  const { mutate: mutateGetDepartments } = useGetDepartments(undefined as any);
  const { mutate: mutateGetOrganizations } = useGetOrganizations(undefined as any);
  const [inputState, setInputState] = useState<UserInputType>(CONTROL_NEW_USER);
  const { userData } = useContext(AuthContext);

  const getDefaultRoleForCreator = () => {
    if (userData?.role === "root") return "super_admin";
    return "business_user";
  };

  function handleInput({
    target: { name, value },
  }: inputHandlerEventType): void {
    setInputState((prev) => ({ ...prev, [name]: value }));
  }

  useEffect(() => {
    if (open) {
      setSubmitError(null);
      if (!data) {
        resetForm();
      } else {
        setUserName(data.username);
        setIsActive(data.is_active);
        const nextRole = data.role ?? "business_user";
        setSelectedRole(nextRole);
        setDepartmentId(data.department_id ?? "");
        setDepartmentName(data.department_name ?? "");
        setOrganizationName(data.organization_name ?? "");
        setOrganizationDescription(data.organization_description ?? "");
        setExpiresAt(data.expires_at ? data.expires_at.slice(0, 16) : "");
        setDepartmentError("");
        setOrganizationError("");

        handleInput({ target: { name: "username", value: data.username } });
        handleInput({ target: { name: "is_active", value: data.is_active } });
        handleInput({ target: { name: "role", value: nextRole } });
      }
    }
  }, [open, data]);

  useEffect(() => {
    if (open) {
      mutateGetAssignableRoles(undefined, {
        onSuccess: (roleNames) => {
          const fallbackRoles = ["super_admin", "leader_executive", "department_admin", "developer", "business_user"];
          const merged = (roleNames || []).length > 0 ? (roleNames || []) : fallbackRoles;
          const filtered = merged.filter((role) => role !== "consumer");
          const withSelected =
            selectedRole && selectedRole !== "consumer" && !filtered.includes(selectedRole)
              ? [...filtered, selectedRole]
              : filtered;
          setAvailableRoles(withSelected);
        },
        onError: () => {
          // Fallback roles if API fails
          const fallbackRoles = ["super_admin", "leader_executive", "department_admin", "developer", "business_user"];
          setAvailableRoles(fallbackRoles);
        },
      });
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (userData?.role !== "super_admin") return;
    mutateGetDepartments(undefined, {
      onSuccess: (res) => {
        setDepartments(
          (res ?? []).map((dept) => ({
            id: dept.id,
            name: dept.name,
            org_id: dept.org_id,
          })),
        );
      },
      onError: () => {
        setDepartments([]);
      },
    });
  }, [open, userData?.role]);

  useEffect(() => {
    if (!open) return;
    if (userData?.role !== "root") return;
    mutateGetOrganizations(undefined, {
      onSuccess: (res) => {
        setOrganizations(
          (res ?? []).map((org) => ({
            id: org.id,
            name: org.name,
            status: org.status,
          })),
        );
      },
      onError: () => {
        setOrganizations([]);
      },
    });
  }, [open, userData?.role]);

  function resetForm() {
    const defaultRole = getDefaultRoleForCreator();
    setUserName("");
    setIsActive(false);
    setSelectedRole(defaultRole);
    setExpiresAt("");
    setDepartmentId("");
    setDepartmentName("");
    setOrganizationName("");
    setOrganizationDescription("");
    setDepartmentError("");
    setOrganizationError("");
    setUsernameError("");
    setInputState({ ...CONTROL_NEW_USER, role: defaultRole });
  }

  function handleRoleChange(selectedRole: string) {
    setSelectedRole(selectedRole);
    handleInput({ target: { name: "role", value: selectedRole } });
    setAvailableRoles((prev) => {
      if (!prev || prev.length === 0) return prev;
      return prev.includes(selectedRole) ? prev : [...prev, selectedRole];
    });
    if (selectedRole === "department_admin") {
      setDepartmentId("");
      setDepartmentError("");
    }
  }

  // Helper function to format role for display
  function formatRoleDisplay(role: string) {
    return role.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  }

  const isRootAdmin = userData?.role === "root";
  const effectiveRole = isRootAdmin ? "super_admin" : (selectedRole || "business_user");
  const isSuperAdmin = userData?.role === "super_admin";
  const isDepartmentAdminCreator = userData?.role === "department_admin";
  const isCreatingSuperAdmin = effectiveRole === "super_admin";
  const isCreatingDepartmentAdmin = effectiveRole === "department_admin";
  const adminExcludedRoles = ["root", "super_admin", "department_admin"];
  const isDepartmentAssignableRole = !adminExcludedRoles.includes(effectiveRole) && effectiveRole !== "leader_executive";
  const enableBulkDepartmentAdd =
    !data && (isDepartmentAdminCreator || isSuperAdmin) && isDepartmentAssignableRole;
  const requiresOrganizationBootstrap = isRootAdmin && isCreatingSuperAdmin;
  const requiresDepartmentAdminSelection =
    isSuperAdmin && (effectiveRole === "developer" || effectiveRole === "business_user");
  const rolesToRender = (() => {
    let baseRoles: string[] = [];
    if (isRootAdmin) {
      baseRoles = ["super_admin"];
    } else if (isSuperAdmin) {
      baseRoles =
        availableRoles.length > 0
          ? availableRoles.filter((role) => !["root", "super_admin"].includes(role))
          : ["leader_executive", "department_admin", "developer", "business_user"];
    } else if (isDepartmentAdminCreator) {
      baseRoles =
        availableRoles.length > 0
          ? availableRoles.filter(
              (role) => !["root", "super_admin", "department_admin"].includes(role),
            )
          : ["developer", "business_user"];
    } else if (availableRoles.length > 0) {
      baseRoles = availableRoles;
    } else {
      baseRoles = ["super_admin", "leader_executive", "department_admin", "developer", "business_user"];
    }
    if (isRootAdmin) {
      return ["super_admin"];
    }
    return Array.from(
      new Set([...baseRoles, effectiveRole].filter((role) => Boolean(role) && role !== "consumer")),
    );
  })();

  function validateDepartmentAdminSelection(): boolean {
    if (!requiresDepartmentAdminSelection) return true;
    if (!departmentId) {
      setDepartmentError("Please select a department.");
      return false;
    }
    const exists = departments.some((dept) => dept.id === departmentId);
    if (!exists) {
      setDepartmentError("Please select a valid department.");
      return false;
    }
    setDepartmentError("");
    return true;
  }

  function validateUsernameEmail(value: string): boolean {
    const trimmed = value.trim();
    if (!trimmed) {
      setUsernameError("Username is required.");
      return false;
    }
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(trimmed)) {
      setUsernameError("Username must be a valid email address.");
      return false;
    }
    setUsernameError("");
    return true;
  }

  function parseBulkUsernames(value: string): string[] {
    return Array.from(
      new Set(
        value
          .split(/[\n,;]+/)
          .map((entry) => entry.trim())
          .filter(Boolean),
      ),
    );
  }

  function normalizeNameKey(value: string | null | undefined): string {
    return (value ?? "").trim().toLowerCase();
  }

  function validateOrganizationNameUniqueness(): boolean {
    if (!requiresOrganizationBootstrap) return true;
    const normalizedName = normalizeNameKey(organizationName);
    if (!normalizedName) return true;
    const existingNormalized = normalizeNameKey(data?.organization_name);
    const duplicate = organizations.some((org) => {
      const candidate = normalizeNameKey(org.name);
      return (
        String(org.status ?? "active").toLowerCase() === "active" &&
        candidate === normalizedName &&
        candidate !== existingNormalized
      );
    });
    if (duplicate) {
      setOrganizationError("An organization with this name already exists.");
      return false;
    }
    setOrganizationError("");
    return true;
  }

  function validateDepartmentNameUniqueness(): boolean {
    if (!isCreatingDepartmentAdmin) return true;
    const normalizedName = normalizeNameKey(departmentName);
    if (!normalizedName) return true;

    const normalizedOrganizationName = normalizeNameKey(
      organizationName || organizations[0]?.name,
    );
    if (normalizedOrganizationName && normalizedName === normalizedOrganizationName) {
      setDepartmentError("Department name cannot be the same as the organization name.");
      return false;
    }

    const scopedOrgIds = Array.from(
      new Set(departments.map((dept) => String(dept.org_id || ""))),
    ).filter(Boolean);

    if (scopedOrgIds.length !== 1) {
      setDepartmentError("");
      return true;
    }

    const existingNormalized = normalizeNameKey(data?.department_name);
    const duplicate = departments.some((dept) => {
      const candidate = normalizeNameKey(dept.name);
      return (
        String(dept.org_id) === scopedOrgIds[0] &&
        candidate === normalizedName &&
        candidate !== existingNormalized
      );
    });

    if (duplicate) {
      setDepartmentError("A department with this name already exists in the organization.");
      return false;
    }

    setDepartmentError("");
    return true;
  }

  function validateUsernameInput(value: string, allowBulk: boolean): boolean {
    if (!allowBulk) {
      return validateUsernameEmail(value);
    }

    const parsed = parseBulkUsernames(value);
    if (parsed.length === 0) {
      setUsernameError("At least one username is required.");
      return false;
    }

    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const invalid = parsed.filter((entry) => !emailPattern.test(entry));
    if (invalid.length > 0) {
      setUsernameError(
        `Invalid email(s): ${invalid.slice(0, 3).join(", ")}${invalid.length > 3 ? "..." : ""}`,
      );
      return false;
    }

    setUsernameError("");
    return true;
  }

  function getSubmitData() {
    const parsedBulkUsernames = enableBulkDepartmentAdd
      ? parseBulkUsernames(username)
      : [username.trim()];
    const submitData: any = {
      username: parsedBulkUsernames[0] ?? "",
      ...(enableBulkDepartmentAdd ? { usernames: parsedBulkUsernames } : {}),
      is_active: isActive,
      role: effectiveRole,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
    };

    if (isCreatingDepartmentAdmin) {
      submitData.department_name = departmentName;
      submitData.department_admin_email = "";
      delete submitData.department_id;
    } else if (isDepartmentAdminCreator) {
      submitData.department_admin_email = userData?.username || "";
      submitData.department_name = (userData as any)?.department_name || "";
      if ((userData as any)?.department_id) {
        submitData.department_id = (userData as any).department_id;
      } else {
        delete submitData.department_id;
      }
    } else if (requiresDepartmentAdminSelection) {
      submitData.department_id = departmentId;
      submitData.department_admin_email = "";
    }
    if (requiresOrganizationBootstrap) {
      submitData.organization_name = organizationName.trim();
      submitData.organization_description = organizationDescription.trim();
    }

    return submitData;
  }

  async function canProceedWithDepartmentChange(): Promise<boolean> {
    if (
      !data?.id ||
      !requiresDepartmentAdminSelection ||
      !departmentId ||
      String(departmentId) === String(data?.department_id ?? "")
    ) {
      return true;
    }

    try {
      const response = await api.get(`${getURL("USERS")}/${data.id}/department-change-check`, {
        params: { target_department_id: departmentId },
      });
      if (response.data?.can_change === false) {
        setDepartmentError(response.data?.detail || "Department change is blocked.");
        return false;
      }
      setDepartmentError("");
      return true;
    } catch (error: any) {
      setDepartmentError(
        error?.response?.data?.detail || error?.message || "Department change check failed.",
      );
      return false;
    }
  }

  return (
    <BaseModal
      size="medium-h-full"
      open={open}
      setOpen={(next) => {
        if (isSubmitting && !next) return;
        setOpen(next);
      }}
    >
      <BaseModal.Trigger asChild={asChild}>{children}</BaseModal.Trigger>
      <BaseModal.Header description={titleHeader}>
        <span className="pr-2">{title}</span>
        <IconComponent
          name={icon}
          className="h-6 w-6 pl-1 text-foreground"
          aria-hidden="true"
        />
      </BaseModal.Header>
      <BaseModal.Content>
        <Form.Root
          onSubmit={async (event) => {
            event.preventDefault();
            if (isSubmitting) return;
            if (!validateUsernameInput(username, enableBulkDepartmentAdd)) {
              return;
            }
            const submitRequiresDepartmentAdminSelection =
              userData?.role === "super_admin" &&
              (effectiveRole === "developer" || effectiveRole === "business_user");
            if (submitRequiresDepartmentAdminSelection && !validateDepartmentAdminSelection()) {
              return;
            }
            if (requiresOrganizationBootstrap && !organizationName.trim()) {
              setOrganizationError("Organization name is required.");
              return;
            }
            if (!validateOrganizationNameUniqueness()) {
              return;
            }
            if (!validateDepartmentNameUniqueness()) {
              return;
            }
            if (!(await canProceedWithDepartmentChange())) {
              return;
            }
            const submitData = getSubmitData();

            // Keep the modal open while the request is in flight: the Save
            // button shows a spinner and stays disabled, and any backend
            // error (e.g. "department admin still has users under them")
            // surfaces inline immediately instead of as a delayed toast that
            // pops up seconds after the modal has already closed.
            setIsSubmitting(true);
            setSubmitError(null);
            try {
              await onConfirm(1, submitData);
              resetForm();
              setOpen(false);
            } catch (err: any) {
              setSubmitError(
                err?.response?.data?.detail ||
                  err?.message ||
                  "Failed to save user. Please try again.",
              );
            } finally {
              setIsSubmitting(false);
            }
          }}
        >
          <div className="grid gap-5">
            <Form.Field name="username">
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                }}
              >
                <Form.Label className="data-[invalid]:label-invalid">
                  {!data &&
                  enableBulkDepartmentAdd
                    ? "Usernames"
                    : "Username"}{" "}
                  <span className="font-medium text-destructive">*</span>
                </Form.Label>
              </div>
              <Form.Control asChild>
                {!data &&
                enableBulkDepartmentAdd ? (
                  <textarea
                    onChange={({ target: { value } }) => {
                      handleInput({ target: { name: "username", value } });
                      setUserName(value);
                      if (usernameError) {
                        validateUsernameInput(value, true);
                      }
                    }}
                    value={username}
                    className="textarea-primary min-h-[110px] w-full resize-y"
                    required
                    placeholder="Enter multiple emails separated by comma or new line"
                  />
                ) : (
                  <input
                    onChange={({ target: { value } }) => {
                      handleInput({ target: { name: "username", value } });
                      setUserName(value);
                      if (usernameError) {
                        validateUsernameInput(value, false);
                      }
                    }}
                    value={username}
                    className="primary-input"
                    required
                    placeholder="Username"
                  />
                )}
              </Form.Control>
              {!data &&
                enableBulkDepartmentAdd && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    Add multiple user emails at once for this department role.
                  </div>
                )}
              {usernameError && (
                <div className="mt-1 text-xs text-destructive">
                  {usernameError}
                </div>
              )}
              <Form.Message match="valueMissing" className="field-invalid">
                Please enter your username
              </Form.Message>
            </Form.Field>

            <div className="flex gap-8">
              <Form.Field name="is_active">
                <div>
                  <Form.Label className="data-[invalid]:label-invalid mr-3">
                    Active
                  </Form.Label>
                  <Form.Control asChild>
                    <Checkbox
                      value={isActive}
                      checked={isActive}
                      id="is_active"
                      className="relative top-0.5"
                      onCheckedChange={(value) => {
                        const nextValue = value === true;
                        handleInput({ target: { name: "is_active", value: nextValue } });
                        setIsActive(nextValue);
                      }}
                    />
                  </Form.Control>
                </div>
              </Form.Field>
              
              <Form.Field name="role">
                <div className="flex flex-col">
                  <Form.Label className="data-[invalid]:label-invalid mb-2">
                    Role{" "}
                    <span className="font-medium text-destructive">*</span>
                  </Form.Label>
                  <select
                    value={effectiveRole}
                    name="role"
                    onChange={(e) => handleRoleChange(e.target.value)}
                    className="primary-input cursor-pointer"
                    required
                  >
                    {rolesToRender.map((r) => (
                      <option key={r} value={r}>
                        {formatRoleDisplay(r)}
                      </option>
                    ))}
                  </select>
                </div>
              </Form.Field>
            </div>

            <Form.Field name="expires_at">
              <div className="flex flex-col">
                <Form.Label className="data-[invalid]:label-invalid mb-2">
                  Expiry Date{" "}
                  <span className="text-xs text-muted-foreground">(optional)</span>
                </Form.Label>
                <DateTimePicker
                  value={expiresAt}
                  onChange={(value) => setExpiresAt(value)}
                  min={new Date().toISOString().slice(0, 16)}
                  placeholder="No expiry — pick a date"
                />
                <div className="mt-1.5">
                  <span className="text-xs text-muted-foreground">
                    {expiresAt ? "User will be deactivated after this date." : "No expiry set — user will not expire."}
                  </span>
                </div>
              </div>
            </Form.Field>

            {isCreatingDepartmentAdmin && (
              <Form.Field name="department_name">
                <div className="flex flex-col">
                  <Form.Label className="data-[invalid]:label-invalid mb-2">
                    Department Name{" "}
                    <span className="font-medium text-destructive">*</span>
                  </Form.Label>
                  <Form.Control asChild>
                    <input
                      onChange={({ target: { value } }) => {
                        setDepartmentName(value);
                        setDepartmentError("");
                      }}
                      value={departmentName}
                      className="primary-input"
                      required
                      placeholder="Department name"
                    />
                  </Form.Control>
                  {departmentError && (
                    <div className="mt-1 text-xs text-destructive">
                      {departmentError}
                    </div>
                  )}
                </div>
              </Form.Field>
            )}
            {requiresOrganizationBootstrap && (
              <div className="grid gap-4">
                <Form.Field name="organization_name">
                  <div className="flex flex-col">
                    <Form.Label className="data-[invalid]:label-invalid mb-2">
                      Organization Name{" "}
                      <span className="font-medium text-destructive">*</span>
                    </Form.Label>
                    <Form.Control asChild>
                      <input
                        onChange={({ target: { value } }) => {
                          setOrganizationName(value);
                          setOrganizationError("");
                        }}
                        value={organizationName}
                        className="primary-input"
                        required
                        placeholder="Organization name"
                      />
                    </Form.Control>
                    {organizationError && (
                      <div className="mt-1 text-xs text-destructive">
                        {organizationError}
                      </div>
                    )}
                  </div>
                </Form.Field>
                <Form.Field name="organization_description">
                  <div className="flex flex-col">
                    <Form.Label className="data-[invalid]:label-invalid mb-2">
                      Organization Description
                    </Form.Label>
                    <Form.Control asChild>
                      <input
                        onChange={({ target: { value } }) => {
                          setOrganizationDescription(value);
                        }}
                        value={organizationDescription}
                        className="primary-input"
                        placeholder="Optional description"
                      />
                    </Form.Control>
                  </div>
                </Form.Field>
              </div>
            )}

            {requiresDepartmentAdminSelection && (
              <Form.Field name="department_id">
                <div className="flex flex-col">
                  <Form.Label className="data-[invalid]:label-invalid mb-2">
                    Department{" "}
                    <span className="font-medium text-destructive">*</span>
                  </Form.Label>
                  <select
                    name="department_id"
                    value={departmentId}
                    onChange={(e) => {
                      setDepartmentId(String(e.target.value || ""));
                      setDepartmentError("");
                    }}
                    className="primary-input"
                    required
                  >
                    <option value="">Select department</option>
                    {departments.map((dept) => (
                      <option key={String(dept.id)} value={String(dept.id)}>
                        {dept.name}
                      </option>
                    ))}
                  </select>
                  {departmentError && (
                    <div className="mt-1 text-xs text-destructive">
                      {departmentError}
                    </div>
                  )}
                </div>
              </Form.Field>
            )}

          </div>

          {submitError ? (
            <div className="mt-4 rounded-md border border-status-red/30 bg-error-background/40 px-3 py-2 text-sm text-error-foreground">
              {submitError}
            </div>
          ) : null}

          <div className="float-right">
            <Button
              variant="outline"
              onClick={() => {
                setOpen(false);
              }}
              className="mr-3"
              disabled={isSubmitting}
            >
              {cancelText}
            </Button>

            <Form.Submit asChild>
              <Button className="mt-8" loading={isSubmitting}>
                {confirmationText}
              </Button>
            </Form.Submit>
          </div>
        </Form.Root>
      </BaseModal.Content>
    </BaseModal>
  );
}
