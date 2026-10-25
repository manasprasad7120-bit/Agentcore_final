import { Cross2Icon } from "@radix-ui/react-icons";
import { ChevronRight } from "lucide-react";
import { forwardRef, useEffect, useRef, useState } from "react";
import IconComponent from "../../components/common/genericIconComponent";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "../../components/ui/popover";
import { ZERO_NOTIFICATIONS } from "../../constants/constants";
import useAlertStore from "../../stores/alertStore";
import type { AlertDropdownType } from "../../types/alerts";
import SingleAlert from "./components/singleAlertComponent";

function resolveNotificationRoute(title: string): string | null {
  const t = title.toLowerCase();
  // Control panel — UAT→PROD promotions and UAT/PROD publish events
  if (
    t.includes("moved to prod") ||
    t.includes("stopped in uat") ||
    t.includes("deployed to uat") ||
    t.includes("deployed to prod") ||
    t.includes("promoted to prod") ||
    t.includes("published to uat") ||
    t.includes("published to prod") ||
    t.startsWith("uat:") ||
    t.startsWith("prod:")
  ) return "/workflows";
  // Approval — submission waiting for review
  if (
    t.includes("submitted for prod approval") ||
    t.includes("approved") || t.includes("rejected") || t.includes("approval") ||
    t.includes("submitted for review") || t.includes("marked as deployed") ||
    t.includes("pending review") || t.includes("under review")
  ) return "/approval";
  if (
    t.includes("user ") || t.includes("user(s)") ||
    t.includes("success! user") || t.includes("error on edit user") ||
    t.includes("error when adding new user")
  ) return "/admin";
  if (t.includes("model")) return "/model-catalogue";
  if (t.includes("mcp")) return "/mcp-servers";
  if (t.includes("package")) return "/packages";
  return null;
}

function isRecentNotification(created_at?: string): boolean {
  if (!created_at) return true; // treat undated as recent
  const created = new Date(created_at);
  const now = new Date();
  // start of yesterday (2 full days back from start of today)
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  return created >= yesterday;
}

const AlertDropdown = forwardRef<HTMLDivElement, AlertDropdownType>(
  function AlertDropdown(
    {
      children,
      notificationRef,
      onClose,
      serverNotifications = [],
      markServerNotificationRead,
      markAllServerNotificationsRead,
    },
    ref,
  ) {
    const notificationList = useAlertStore((state) => state.notificationList);
    const clearNotificationList = useAlertStore(
      (state) => state.clearNotificationList,
    );
    const removeFromNotificationList = useAlertStore(
      (state) => state.removeFromNotificationList,
    );
    const setNotificationCenter = useAlertStore(
      (state) => state.setNotificationCenter,
    );
    const [open, setOpen] = useState(false);
    const [showOlder, setShowOlder] = useState(false);
    // IDs that were visible when the panel last closed — rendered as muted/seen
    const [seenIds, setSeenIds] = useState<Set<string>>(new Set());
    // Accumulate IDs visible in the current open session; committed to seenIds on close
    const pendingSeenRef = useRef<Set<string>>(new Set());

    const serverTitles = new Set(serverNotifications.map((n) => n.title));

    const mergedNotifications = [
      ...serverNotifications.map((item) => {
        const loweredTitle = item.title.toLowerCase();
        const type = loweredTitle.includes("was approved") || loweredTitle.includes("was deployed")
          ? ("success" as const)
          : loweredTitle.includes("was rejected")
            ? ("error" as const)
            : ("notice" as const);

        return {
          id: `server:${item.id}`,
          type,
          title: item.title,
          link: item.link ?? undefined,
          created_at: item.created_at,
          is_read: item.is_read ?? false,
        };
      }),
      ...notificationList.filter((n) => !serverTitles.has(n.title)),
    ];

    const recentNotifications = mergedNotifications.filter((n) =>
      isRecentNotification(n.created_at),
    );
    const olderNotifications = mergedNotifications.filter(
      (n) => !isRecentNotification(n.created_at),
    );

    // When the panel opens, start collecting visible IDs
    useEffect(() => {
      if (open) {
        mergedNotifications.forEach((n) => pendingSeenRef.current.add(n.id));
      } else {
        // Panel closed: commit pending IDs to seenIds and fire onClose
        if (pendingSeenRef.current.size > 0) {
          setSeenIds((prev) => {
            const next = new Set(prev);
            pendingSeenRef.current.forEach((id) => next.add(id));
            return next;
          });
          pendingSeenRef.current = new Set();
        }
        setShowOlder(false);
        onClose?.();
      }
    }, [open]);

    const renderAlert = (alertItem: (typeof mergedNotifications)[number]) => {
      // Ignore "/" — backend stores it as the fallback when no real link was given
      const explicitLink = alertItem.link && alertItem.link !== "/" ? alertItem.link : null;
      const navigateTo =
        explicitLink || resolveNotificationRoute(alertItem.title) || undefined;
      return (
        <SingleAlert
          key={alertItem.id}
          dropItem={alertItem}
          removeAlert={(id) => {
            if (id.startsWith("server:")) {
              markServerNotificationRead?.(id.replace("server:", ""));
              return;
            }
            removeFromNotificationList(id);
          }}
          navigateTo={navigateTo}
          onClosePanel={() => setOpen(false)}
          isSeen={seenIds.has(alertItem.id) || Boolean((alertItem as any).is_read)}
        />
      );
    };

    return (
      <Popover
        data-testid="notification-dropdown"
        open={open}
        onOpenChange={(target) => {
          setOpen(target);
          if (target) {
            setNotificationCenter(false);
          }
        }}
      >
        <PopoverTrigger asChild>{children}</PopoverTrigger>
        <PopoverContent
          ref={notificationRef}
          data-testid="notification-dropdown-content"
          className="noflow nowheel nopan nodelete nodrag z-50 flex h-[min(500px,80vh)] w-[min(500px,calc(100vw-2rem))] flex-col"
        >
          <div className="text-md flex flex-row justify-between pl-3 font-medium text-foreground">
            Notifications
            <div className="flex gap-3 pr-3">
              <button
                className="text-muted-foreground hover:text-status-red"
                onClick={() => {
                  setOpen(false);
                  markAllServerNotificationsRead?.();
                  setTimeout(clearNotificationList, 100);
                }}
              >
                <IconComponent name="Trash2" className="h-4 w-4" />
              </button>
              <button
                className="text-foreground opacity-70 hover:opacity-100"
                onClick={() => {
                  setOpen(false);
                }}
              >
                <Cross2Icon className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="text-high-foreground mt-3 flex h-full w-full flex-col overflow-y-scroll scrollbar-hide">
            {mergedNotifications.length !== 0 ? (
              <>
                {recentNotifications.map(renderAlert)}

                {olderNotifications.length > 0 && (
                  <>
                    {showOlder ? (
                      <>
                        <div className="mx-2 mb-1 mt-1 flex items-center gap-2">
                          <div className="h-px flex-1 bg-border" />
                          <span className="text-xs text-muted-foreground">Older</span>
                          <div className="h-px flex-1 bg-border" />
                        </div>
                        {olderNotifications.map(renderAlert)}
                      </>
                    ) : (
                      <button
                        className="mx-2 mb-2 mt-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        onClick={() => setShowOlder(true)}
                      >
                        <ChevronRight className="h-3 w-3" />
                        {olderNotifications.length} more notification
                        {olderNotifications.length !== 1 ? "s" : ""}
                      </button>
                    )}
                  </>
                )}

                {recentNotifications.length === 0 && olderNotifications.length === 0 && (
                  <div className="flex h-full w-full items-center justify-center pb-16 text-ring">
                    {ZERO_NOTIFICATIONS}
                  </div>
                )}
              </>
            ) : (
              <div className="flex h-full w-full items-center justify-center pb-16 text-ring">
                {ZERO_NOTIFICATIONS}
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>
    );
  },
);

export default AlertDropdown;
