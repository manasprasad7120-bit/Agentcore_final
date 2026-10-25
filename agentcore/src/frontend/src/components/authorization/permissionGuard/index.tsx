import useAuthStore from "@/stores/authStore";
import { LoadingPage } from "@/pages/LoadingPage";
import AccessDeniedPage from "@/pages/AccessDeniedPage";

export const ProtectedPermissionRoute = ({
  children,
  permission,
  permissions,
}: {
  children: JSX.Element;
  permission?: string;
  permissions?: string[];
}) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userPermissions = useAuthStore((state) => state.permissions);
  const role = useAuthStore((state) => state.role);

  if (!isAuthenticated) {
    return <LoadingPage />;
  }

  if (String(role ?? "").toLowerCase() === "root") {
    return children;
  }

  const requiredPermissions = permissions?.filter(Boolean) ?? (permission ? [permission] : []);
  const hasPermission =
    requiredPermissions.length === 0 ||
    requiredPermissions.some((requiredPermission) => userPermissions.includes(requiredPermission));

  if (!hasPermission) {
    return (
      <AccessDeniedPage
        message={`Missing permission: ${requiredPermissions.join(" or ")}`}
      />
    );
  }

  return children;
};
