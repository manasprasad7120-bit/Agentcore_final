const DASHBOARD_REFRESH_EVENT = "dashboard-refresh";
const DASHBOARD_REFRESH_CHANNEL = "agentcore-dashboard-refresh";

export const emitDashboardRefresh = () => {
  if (typeof window === "undefined") return;

  window.dispatchEvent(new Event(DASHBOARD_REFRESH_EVENT));

  if ("BroadcastChannel" in window) {
    const channel = new BroadcastChannel(DASHBOARD_REFRESH_CHANNEL);
    channel.postMessage({ type: DASHBOARD_REFRESH_EVENT, ts: Date.now() });
    channel.close();
  }
};

export const subscribeDashboardRefresh = (handler: () => void) => {
  if (typeof window === "undefined") return () => {};

  const onEvent = () => handler();
  window.addEventListener(DASHBOARD_REFRESH_EVENT, onEvent);

  let channel: BroadcastChannel | null = null;
  const onMessage = (event: MessageEvent) => {
    if (event?.data?.type === DASHBOARD_REFRESH_EVENT) {
      handler();
    }
  };

  if ("BroadcastChannel" in window) {
    channel = new BroadcastChannel(DASHBOARD_REFRESH_CHANNEL);
    channel.addEventListener("message", onMessage);
  }

  return () => {
    window.removeEventListener(DASHBOARD_REFRESH_EVENT, onEvent);
    if (channel) {
      channel.removeEventListener("message", onMessage);
      channel.close();
    }
  };
};
