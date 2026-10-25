import { useEffect } from "react";
import { useLogout, useRefreshAccessToken } from "@/controllers/API/queries/auth";
import { CustomNavigate } from "@/customization/components/custom-navigate";
import { customGetAccessToken } from "@/customization/utils/custom-get-access-token";
import useAuthStore from "@/stores/authStore";

const TOKEN_REFRESH_BUFFER_SECONDS = 15;
const MIN_TOKEN_REFRESH_SECONDS = 5;
const FALLBACK_REFRESH_SECONDS = 60;

const getAccessTokenExpEpoch = (token: string | undefined): number | null => {
  if (!token) return null;

  try {
    const payloadPart = token.split(".")[1];
    if (!payloadPart) return null;

    const normalized = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const payload = JSON.parse(atob(padded));
    return typeof payload?.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
};

export const ProtectedRoute = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const { mutate: mutateRefresh } = useRefreshAccessToken();
  const { mutate: mutateLogout } = useLogout();

  
  const testMockAutoLogin = sessionStorage.getItem("testMockAutoLogin");

  const shouldRedirect = !isAuthenticated;

  useEffect(() => {
    if (!isAuthenticated) return;

    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const clearScheduledRefresh = () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = undefined;
      }
    };

    const logoutStaleSession = () => {
      if (cancelled) return;
      clearScheduledRefresh();
      mutateLogout(undefined);
    };

    const refreshSession = () => {
      if (cancelled) return;

      mutateRefresh(undefined, {
        onSuccess: () => {
          if (!cancelled) {
            scheduleRefresh();
          }
        },
        onError: () => {
          logoutStaleSession();
        },
      });
    };

    const scheduleRefresh = () => {
      if (cancelled) return;
      clearScheduledRefresh();

      const currentToken = customGetAccessToken();
      const tokenExp = getAccessTokenExpEpoch(currentToken);
      const now = Math.floor(Date.now() / 1000);
      const secondsUntilExpiry = tokenExp ? tokenExp - now : null;

      const nextRefreshInSeconds =
        secondsUntilExpiry === null
          ? FALLBACK_REFRESH_SECONDS
          : Math.max(
              MIN_TOKEN_REFRESH_SECONDS,
              secondsUntilExpiry - TOKEN_REFRESH_BUFFER_SECONDS,
            );

      timeoutId = setTimeout(() => {
        refreshSession();
      }, nextRefreshInSeconds * 1000);
    };

    const refreshIfNeeded = () => {
      if (cancelled) return;

      const currentToken = customGetAccessToken();
      const tokenExp = getAccessTokenExpEpoch(currentToken);
      const now = Math.floor(Date.now() / 1000);
      const secondsUntilExpiry = tokenExp ? tokenExp - now : null;

      if (secondsUntilExpiry === null || secondsUntilExpiry <= TOKEN_REFRESH_BUFFER_SECONDS) {
        refreshSession();
        return;
      }

      scheduleRefresh();
    };

    const onFocus = () => {
      refreshIfNeeded();
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshIfNeeded();
      }
    };

    scheduleRefresh();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      cancelled = true;
      clearScheduledRefresh();
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [isAuthenticated, mutateLogout, mutateRefresh]);

  if (shouldRedirect || testMockAutoLogin) {
    // Preserve the query string (e.g. shared-chat `?session=<id>`) so the
    // post-login redirect lands the user on the same deep link they opened.
    const currentPath = window.location.pathname + window.location.search;
    const isHomePath = currentPath === "/" || currentPath === "/agents";
    const isLoginPage = location.pathname.includes("login");
    return (
      <CustomNavigate
        to={
          "/login" +
          (!isHomePath && !isLoginPage
            ? "?redirect=" + encodeURIComponent(currentPath)
            : "")
        }
        replace
      />
    );
  } else {
    return children;
  }
};
