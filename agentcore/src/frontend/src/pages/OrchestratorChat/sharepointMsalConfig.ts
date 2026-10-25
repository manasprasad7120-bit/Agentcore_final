/**
 * Dedicated MSAL instance for SharePoint integration in OrchestratorChat.
 *
 * Uses MiBuddy's Azure AD App Registration (which is already approved for
 * Motherson users), separate from agentcore's main login MSAL instance.
 *
 * This avoids the "Request sent — admin notified" error that occurs when
 * Motherson users try to consent to the agentcore tenant app.
 */
import { PublicClientApplication, type Configuration } from "@azure/msal-browser";

// Sourced from SHAREPOINT_TENANT_ID / SHAREPOINT_CLIENT_ID in the root .env
// (wired through vite.config.mts `define`). Falls back to the previous
// hardcoded MiBuddy values so existing dev environments keep working.
const SHAREPOINT_TENANT_ID =
  process.env.SHAREPOINT_TENANT_ID || "7a746742-7931-4f5d-8af3-d2bf6fbb3a15";
const SHAREPOINT_CLIENT_ID =
  process.env.SHAREPOINT_CLIENT_ID || "1994098f-d8c0-4ebe-bde0-b2fcc5db5fcb";

export const sharepointMsalConfig: Configuration = {
  auth: {
    clientId: SHAREPOINT_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${SHAREPOINT_TENANT_ID}`,
    redirectUri: window.location.origin,
    navigateToLoginRequestUrl: false,
  },
  cache: {
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
};

export const sharepointLoginRequest = {
  scopes: ["User.Read", "Files.Read.All", "Sites.Read.All"],
};

// The SharePoint MSAL instance is created and initialized lazily by
// `initSharepointMsal()`, which is called from `src/index.tsx` AFTER the
// main agentcore MSAL instance has finished `handleRedirectPromise()`.
// Creating it at module-load time would collide with the main instance in
// sessionStorage and cause "interaction_in_progress" errors on the login
// page.  After init, `getSharepointMsalInstance()` returns it synchronously
// so click handlers never need to `await` before calling `loginPopup`.
let _instance: PublicClientApplication | null = null;
let _initPromise: Promise<PublicClientApplication> | null = null;

/**
 * Create + initialize the SharePoint MSAL instance. Safe to call multiple
 * times — only the first call does real work; subsequent calls return the
 * same promise.  The instance is created lazily (NOT at module-load time)
 * to avoid colliding with the main agentcore MSAL instance in
 * sessionStorage.
 */
export function initSharepointMsal(): Promise<PublicClientApplication> {
  if (!_initPromise) {
    const inst = new PublicClientApplication(sharepointMsalConfig);
    _initPromise = inst
      .initialize()
      .then(() => inst.handleRedirectPromise())
      .then(() => {
        _instance = inst;
        return inst;
      });
  }
  return _initPromise;
}

/**
 * Returns the SharePoint MSAL instance if it has been initialized,
 * otherwise `null`.  Components should call `initSharepointMsal()` in a
 * `useEffect` on mount, then read the synchronous result here in click
 * handlers (no `await` ⇒ popup won't be blocked by the browser).
 */
export function getSharepointMsalInstance(): PublicClientApplication | null {
  return _instance;
}
