import { useEffect } from "react";

/**
 * SharePoint OAuth callback page.
 *
 * Opened as a popup by the orchestrator. Reads the auth code from
 * the URL query params, sends it to the parent window via postMessage,
 * then closes itself.
 */
export default function SharePointCallback() {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const error = params.get("error");
    const state = params.get("state");

    if (window.opener) {
      window.opener.postMessage(
        { type: "sharepoint-auth", code, error, state },
        window.location.origin,
      );
    }
    window.close();
  }, []);

  return (
    <div className="flex h-screen items-center justify-center bg-background text-foreground">
      <p className="text-sm text-muted-foreground">
        Authenticating with SharePoint... This window will close automatically.
      </p>
    </div>
  );
}
