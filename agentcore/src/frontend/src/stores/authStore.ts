import { Cookies } from "react-cookie";
import { create } from "zustand";
import {
  AGENTCORE_ACCESS_TOKEN,
  AGENTCORE_API_TOKEN,
  AGENTCORE_REFRESH_TOKEN,
} from "@/constants/constants";
import type { AuthStoreType } from "@/types/zustand/auth";
import { removeLocalStorage } from "@/utils/local-storage-util";
import { removeAuthCookie } from "@/utils/utils";

const cookies = new Cookies();
const useAuthStore = create<AuthStoreType>((set) => ({
  // auth
  isAuthenticated: !!cookies.get(AGENTCORE_ACCESS_TOKEN),
  accessToken: cookies.get(AGENTCORE_ACCESS_TOKEN) ?? null,
  apiKey: cookies.get(AGENTCORE_API_TOKEN),
  authenticationErrorCount: 0,

  // authz
  role: null,
  permissions: [],
  userData: null,

  // 🔥 hydration
  isAuthHydrated: false,

  setAuthContext: ({ role, permissions }) =>
    set({ role, permissions }),

  setAuthHydrated: (value: boolean) => set({ isAuthHydrated: value }),

  setIsAuthenticated: (isAuthenticated) =>
    set({ isAuthenticated }),

  setAccessToken: (accessToken) =>
    set({ accessToken }),

  setUserData: (userData) =>
    set({ userData }),

  setApiKey: (apiKey) =>
    set({ apiKey }),

  setAuthenticationErrorCount: (authenticationErrorCount) =>
    set({ authenticationErrorCount }),

  logout: async () => {
    removeAuthCookie(cookies, AGENTCORE_ACCESS_TOKEN);
    removeAuthCookie(cookies, AGENTCORE_REFRESH_TOKEN);
    removeAuthCookie(cookies, AGENTCORE_API_TOKEN);
    removeLocalStorage(AGENTCORE_ACCESS_TOKEN);
    removeLocalStorage(AGENTCORE_REFRESH_TOKEN);
    removeLocalStorage(AGENTCORE_API_TOKEN);

    set({
      isAuthenticated: false,
      accessToken: null,
      apiKey: null,
      authenticationErrorCount: 0,
      role: null,
      permissions: [],
      userData: null,
      isAuthHydrated: false,
    });
  },
}));

export default useAuthStore;
