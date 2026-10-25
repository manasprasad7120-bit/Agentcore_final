/**
 * OutlookOrchConnector — pixel-faithful port of MiBuddy's OutlookConnector.
 *
 * Matches MiBuddy's original layout, emoji, copy text, and MS-FluentUI
 * colors (`#107C10` success green, `#fff4ce` privacy-note yellow) while
 * using plain CSS-in-JSX so it stays independent of FluentUI.
 *
 * Talks to the orchestrator-only endpoints under `/api/outlook-orch/...`
 * — the existing `outlook-chat` routes and `OutlookConnector.tsx` are a
 * different use-case and must not be touched.
 */
import { useEffect, useRef, useState } from "react";

interface OutlookOrchConnectorProps {
  isOpen: boolean;
  onDismiss: () => void;
  onConnected: () => void;
}

export default function OutlookOrchConnector({
  isOpen,
  onDismiss,
  onConnected,
}: OutlookOrchConnectorProps) {
  const [loading, setLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const connectingRef = useRef(false);
  const authWindowRef = useRef<Window | null>(null);

  // Match MiBuddy: dark mode read from localStorage on every render so it
  // stays in sync with their existing theme toggle.
  const isDark =
    typeof window !== "undefined" &&
    localStorage.getItem("themeMode") === "dark";

  useEffect(() => {
    if (isOpen) {
      setIsConnected(false);
      return;
    }
    setLoading(false);
    connectingRef.current = false;
    authWindowRef.current = null;
  }, [isOpen]);

  const handleConnect = () => {
    if (connectingRef.current) return;
    connectingRef.current = true;
    setLoading(true);

    const authWindow = window.open(
      "/api/outlook-orch/auth/login",
      "outlookAuth",
      "width=600,height=700",
    );
    authWindowRef.current = authWindow;
    if (!authWindow) {
      connectingRef.current = false;
      setLoading(false);
      alert("Popup blocked. Please allow popups and try again.");
    }
  };

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "OUTLOOK_AUTH_SUCCESS") {
        setIsConnected(true);
        onConnected();
        connectingRef.current = false;
        setLoading(false);
        setTimeout(() => onDismiss(), 1200);
      }
      if (event.data?.type === "OUTLOOK_AUTH_ERROR") {
        connectingRef.current = false;
        setLoading(false);
        alert("Failed to connect to Outlook. Please try again.");
      }
    };
    const timer = window.setInterval(() => {
      if (
        connectingRef.current &&
        authWindowRef.current &&
        authWindowRef.current.closed
      ) {
        connectingRef.current = false;
        setLoading(false);
        authWindowRef.current = null;
      }
    }, 300);
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearInterval(timer);
    };
  }, [onConnected, onDismiss]);

  if (!isOpen) return null;

  /* ── Exact MiBuddy colors ────────────────────────────────────── */
  const GREEN = "#107C10"; // FluentUI success green
  const NOTE_BG_LIGHT = "#fff4ce";
  const NOTE_BG_DARK = "#3d3211";
  const NOTE_BORDER_LIGHT = "#ffb900";
  const NOTE_BORDER_DARK = "#7a6a00";
  const NOTE_TEXT_DARK = "#f0e6c5";
  const CAP_BG_LIGHT = "transparent";
  const CAP_BG_DARK = "#2d2d2e";
  const CAP_BORDER_LIGHT = "#e0e0e0";
  const CAP_BORDER_DARK = "#3a3a3b";
  const DIALOG_BG = isDark ? "#1e1e1f" : "#ffffff";
  const TEXT = isDark ? "#ffffff" : "#333333";
  const SUB_TEXT = isDark ? "#D9D9D9" : "#666666";

  const title = isConnected ? "Outlook Connected!" : "Connect to Outlook";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: "min(600px, 92vw)",
          minWidth: 500,
          maxHeight: "90vh",
          overflow: "auto",
          background: DIALOG_BG,
          borderRadius: 12,
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
          fontFamily:
            "'Segoe UI', -apple-system, 'Inter', system-ui, sans-serif",
        }}
      >
        {/* Header (MiBuddy dialog title) */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "20px 24px 8px 24px",
            color: TEXT,
          }}
        >
          <div style={{ fontSize: 20, fontWeight: 600 }}>{title}</div>
          <button
            aria-label="Close"
            onClick={onDismiss}
            style={{
              background: "transparent",
              border: 0,
              color: SUB_TEXT,
              fontSize: 20,
              cursor: "pointer",
              lineHeight: 1,
              padding: 4,
            }}
          >
            ✕
          </button>
        </div>

        {loading ? (
          /* ── Loading screen (MiBuddy Spinner + text) ── */
          <div
            style={{
              padding: 40,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 20,
              textAlign: "center",
            }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                border: "3px solid #ccc",
                borderTopColor: "#0078D4",
                borderRadius: "50%",
                animation: "outlookOrchSpin 0.8s linear infinite",
              }}
            />
            <div style={{ fontSize: 16, color: SUB_TEXT }}>
              Connecting to your Outlook account...
            </div>
            <style>{`@keyframes outlookOrchSpin{to{transform:rotate(360deg)}}`}</style>
          </div>
        ) : isConnected ? (
          /* ── Connected screen ── */
          <div
            style={{
              padding: 30,
              textAlign: "center",
              display: "flex",
              flexDirection: "column",
              gap: 20,
            }}
          >
            <div style={{ fontSize: 64, marginBottom: 10 }}>✅</div>
            <div style={{ fontSize: 20, fontWeight: 600, color: GREEN }}>
              Successfully Connected!
            </div>
            <div style={{ fontSize: 14, color: SUB_TEXT }}>
              You can now ask questions about your emails and calendar.
            </div>
            <div
              style={{
                background: isDark ? "#2d2d2e" : "#f3f2f1",
                padding: 15,
                borderRadius: 8,
                marginTop: 10,
                textAlign: "left",
                border: isDark ? "1px solid #3a3a3b" : "none",
              }}
            >
              <p
                style={{
                  margin: "0 0 10px 0",
                  fontWeight: 600,
                  fontSize: 14,
                  color: TEXT,
                }}
              >
                Try asking:
              </p>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 20,
                  fontSize: 14,
                  color: isDark ? "#d9d9d9" : "#555",
                }}
              >
                <li>"Show me my recent emails"</li>
                <li>"Do I have any meetings today?"</li>
                <li>"Search for emails from John about the project"</li>
                <li>"What's on my calendar this week?"</li>
              </ul>
            </div>
          </div>
        ) : (
          /* ── Consent screen (matches MiBuddy exactly) ── */
          <div
            style={{
              padding: 20,
              textAlign: "center",
              display: "flex",
              flexDirection: "column",
              gap: 24,
            }}
          >
            <div style={{ fontSize: 48, marginBottom: 10 }}>📧</div>

            <div style={{ fontSize: 16, color: TEXT, lineHeight: 1.5 }}>
              <p style={{ margin: 0, fontWeight: 600, fontSize: 18 }}>
                Connect MiBuddy to your Outlook
              </p>
              <p style={{ color: SUB_TEXT, margin: "4px 0 0 0" }}>
                Access your emails and calendar to get intelligent assistance
              </p>

              {/* Capability card */}
              <div
                style={{
                  padding: 20,
                  borderRadius: 8,
                  textAlign: "left",
                  marginTop: 20,
                  background: isDark ? CAP_BG_DARK : CAP_BG_LIGHT,
                  border: `1px solid ${isDark ? CAP_BORDER_DARK : CAP_BORDER_LIGHT}`,
                }}
              >
                <p
                  style={{
                    margin: "0 0 10px 0",
                    fontWeight: 600,
                    color: TEXT,
                  }}
                >
                  This will allow MiBuddy to:
                </p>
                <ul
                  style={{
                    listStyleType: "none",
                    padding: 0,
                    margin: 0,
                    color: isDark ? "#d9d9d9" : "#333",
                  }}
                >
                  {[
                    "Read your emails and search your mailbox",
                    "View your calendar events and meetings",
                    "Access your profile information",
                  ].map((text, i, arr) => (
                    <li
                      key={text}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        marginBottom: i === arr.length - 1 ? 0 : 12,
                      }}
                    >
                      <span
                        style={{
                          marginRight: 12,
                          color: GREEN,
                          fontWeight: "bold",
                        }}
                      >
                        ✓
                      </span>
                      {text}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Privacy note */}
              <div
                style={{
                  background: isDark ? NOTE_BG_DARK : NOTE_BG_LIGHT,
                  padding: 15,
                  borderRadius: 6,
                  marginTop: 15,
                  border: `1px solid ${isDark ? NOTE_BORDER_DARK : NOTE_BORDER_LIGHT}`,
                  textAlign: "left",
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: 14,
                    color: isDark ? NOTE_TEXT_DARK : "#333",
                  }}
                >
                  <strong>🔒 Privacy Note:</strong> Your emails and calendar
                  data are only accessed when you ask questions. We never store
                  your email content or share it with third parties.
                </p>
              </div>
            </div>

            {/* Footer buttons (MiBuddy PrimaryButton + DefaultButton) */}
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                gap: 10,
                padding: "8px 0 4px 0",
              }}
            >
              <button
                onClick={handleConnect}
                disabled={loading}
                style={{
                  padding: "14px 32px",
                  fontSize: 16,
                  fontWeight: 600,
                  borderRadius: 4,
                  background: "#0078D4",
                  color: "#ffffff",
                  border: "1px solid #0078D4",
                  cursor: loading ? "not-allowed" : "pointer",
                  opacity: loading ? 0.6 : 1,
                }}
              >
                Connect to Outlook
              </button>
              <button
                onClick={onDismiss}
                disabled={loading}
                style={{
                  padding: "14px 24px",
                  fontSize: 16,
                  fontWeight: 600,
                  borderRadius: 4,
                  background: isDark ? "#2d2d2e" : "#ffffff",
                  color: isDark ? "#ffffff" : "#333333",
                  border: `1px solid ${isDark ? "#3a3a3b" : "#8a8886"}`,
                  cursor: loading ? "not-allowed" : "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Auto-reconnect hook — port of MiBuddy's `useOutlookAutoReconnect`.
 * Polls /api/outlook-orch/status once on mount to restore "connected"
 * state after a page reload.
 */
export function useOutlookOrchStatus() {
  const [isOutlookConnected, setIsOutlookConnected] = useState(false);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch("/api/outlook-orch/status", {
          method: "GET",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        if (res.ok) {
          const data = await res.json();
          setIsOutlookConnected(Boolean(data.connected));
        }
      } catch {
        /* ignore — treat as not connected */
      }
    };
    check();
  }, []);

  return { isOutlookConnected, setIsOutlookConnected };
}

/** Disconnect helper (parallel to MiBuddy's inline usage). */
export async function disconnectOutlookOrch(): Promise<void> {
  await fetch("/api/outlook-orch/disconnect", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
}
