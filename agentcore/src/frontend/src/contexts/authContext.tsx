import { createContext, useCallback, useEffect, useState } from "react";
import type { AxiosError } from "axios";
import { Cookies } from "react-cookie";
import {
  AGENTCORE_ACCESS_TOKEN,
  AGENTCORE_API_TOKEN,
  AGENTCORE_REFRESH_TOKEN,
} from "@/constants/constants";
import { useGetUserData } from "@/controllers/API/queries/auth";
import { useLogout } from "@/controllers/API/queries/auth/use-post-logout";
import { useGetGlobalVariablesMutation } from "@/controllers/API/queries/variables/use-get-mutation-global-variables";
import useAuthStore from "@/stores/authStore";
import { getAuthCookie, setAuthCookie } from "@/utils/utils";
import { useStoreStore } from "../stores/storeStore";
import type { Users } from "../types/api";
import type { AuthContextType } from "../types/contexts/auth";

const initialValue: AuthContextType = {
  accessToken: null,
  role: null,            // Match the new type
  permissions: [],
  login: () => {},
  userData: null,
  setUserData: () => {},
  authenticationErrorCount: 0,
  setApiKey: () => {},
  apiKey: null,
  storeApiKey: () => {},
  getUser: () => {},
};

export const AuthContext = createContext<AuthContextType>(initialValue);

export function AuthProvider({ children }): React.ReactElement {
  const cookies = new Cookies();
  const [accessToken, setAccessToken] = useState<string | null>(
    getAuthCookie(cookies, AGENTCORE_ACCESS_TOKEN) ?? null,
  );
  // --- ADD THESE STATES FOR RBAC ---
  const [role, setRole] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  // ---------------------------------
  const [userData, setUserData] = useState<Users | null>(null);
  const [apiKey, setApiKey] = useState<string | null>(
    getAuthCookie(cookies, AGENTCORE_API_TOKEN),
  );

  const checkHasStore = useStoreStore((state) => state.checkHasStore);
  const fetchApiData = useStoreStore((state) => state.fetchApiData);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const storeAccessToken = useAuthStore((state) => state.accessToken);
  const setIsAuthenticated = useAuthStore((state) => state.setIsAuthenticated);
  const setAuthContext = useAuthStore((state) => state.setAuthContext);
  const clearAuthStore = useAuthStore((state) => state.logout);

  const { mutate: mutateLoggedUser } = useGetUserData();
  const { mutate: mutateLogout, mutateAsync: mutateLogoutAsync } = useLogout();
  const { mutate: mutateGetGlobalVariables } = useGetGlobalVariablesMutation();

  const clearLocalAuthState = useCallback(() => {
    setAccessToken(null);
    setRole(null);
    setPermissions([]);
    setUserData(null);
  }, []);

  useEffect(() => {
    const storedAccessToken = getAuthCookie(cookies, AGENTCORE_ACCESS_TOKEN);
    if (storedAccessToken) {
      setAccessToken(storedAccessToken);
    }
  }, []);

  useEffect(() => {
    const apiKey = getAuthCookie(cookies, AGENTCORE_API_TOKEN);
    if (apiKey) {
      setApiKey(apiKey);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) {
      clearLocalAuthState();
      return;
    }

    setAccessToken(storeAccessToken);
  }, [clearLocalAuthState, isAuthenticated, storeAccessToken]);

  const getUser = useCallback(() => {
    mutateLoggedUser(
      {},
      {
        onSuccess: async (user) => {
          if (!user) {
            clearLocalAuthState();
            return;
          }

          // Auto-logout if user account has expired
          if (user.expires_at) {
            const expiresAt = new Date(user.expires_at);
            if (!isNaN(expiresAt.getTime()) && Date.now() >= expiresAt.getTime()) {
              mutateLogout(undefined);
              return;
            }
          }

          setUserData(user);
          useAuthStore.getState().setUserData(user);
          setAuthContext({
            role: user.role,
            permissions: user.permissions,
          });
          setRole(user.role);
          setPermissions(user.permissions || []);


          checkHasStore();
          fetchApiData();
        },
        onError: async (error) => {
          const status = (error as AxiosError)?.response?.status;
          const isTransportFailure =
            !(error as AxiosError)?.response &&
            Boolean((error as AxiosError)?.message);

          if (isTransportFailure) {
            // On deployed environments (AKS), idle connections get dropped by
            // the ingress / load-balancer.  If the session has also expired
            // the backend would return 401 — but the request never reaches it
            // because the stale TCP connection fails first.  Retry once after
            // a short delay so the browser opens a fresh connection and we can
            // distinguish "truly offline" from "session expired on AKS".
            try {
              await new Promise((r) => setTimeout(r, 1500));
              const retryRes = await fetch("/api/users/whoami", {
                credentials: "include",
              });
              if (retryRes.ok) {
                // Retry succeeded — network was just briefly down, session is
                // still valid.  Next scheduled getUser() picks up fresh data.
                return;
              }
              if (retryRes.status !== 401 && retryRes.status !== 403) {
                // Server error but not auth — keep auth state.
                return;
              }
              // 401/403 — session has expired, fall through to logout below.
            } catch {
              // Still a transport failure — genuinely offline, keep auth.
              return;
            }
          }

          clearLocalAuthState();
          useAuthStore.getState().setUserData(null);

          if (status === 401 || status === 403 || isTransportFailure) {
            try {
              await mutateLogoutAsync(undefined);
            } catch {
              await clearAuthStore();
            }
            setIsAuthenticated(false);
          }
        },
      },
    );
  }, [
    mutateLoggedUser,
    mutateLogout,
    mutateLogoutAsync,
    setAuthContext,
    checkHasStore,
    fetchApiData,
    clearAuthStore,
    clearLocalAuthState,
    setIsAuthenticated,
  ]);

  useEffect(() => {
    // Always attempt whoami on mount; backend can read httpOnly cookies.
    getUser();
  }, [getUser]);

  useEffect(() => {
    if (!userData?.id) return;

    // Keep permissions fresh without forcing manual browser refresh.
    const interval = setInterval(() => {
      getUser();
    }, 20 * 1000);

    const onFocus = () => getUser();
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        getUser();
      }
    };

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [userData?.id, getUser]);

  function login(
    newAccessToken: string,
    userRole: string,        
    userPermissions: string[],
    refreshToken?: string,
    
  ) {
    setAuthCookie(cookies, AGENTCORE_ACCESS_TOKEN, newAccessToken);

    if (refreshToken) {
      setAuthCookie(cookies, AGENTCORE_REFRESH_TOKEN, refreshToken);
    }

    setAuthContext({
      role: userRole,
      permissions: userPermissions,
    });
    setRole(userRole);
    setPermissions(userPermissions);


    setAccessToken(newAccessToken);
    setIsAuthenticated(true);
    getUser();
    getGlobalVariables();
  }

  function storeApiKey(apikey: string) {
    setApiKey(apikey);
  }

  function getGlobalVariables() {
    mutateGetGlobalVariables({});
  }

  return (
    // !! to convert string to boolean
    <AuthContext.Provider
      value={{
        accessToken,
        role,          
        permissions,
        login,
        setUserData,
        userData,
        authenticationErrorCount: 0,
        setApiKey,
        apiKey,
        storeApiKey,
        getUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
