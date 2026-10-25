export type ErrorAlertType = {
  title: string;
  list: Array<string> | undefined;
  id: string;
  removeAlert: (id: string) => void;
};
export type NoticeAlertType = {
  title: string;
  link?: string;
  id: string;
  removeAlert: (id: string) => void;
  list?: Array<string>;
};
export type SuccessAlertType = {
  title: string;
  id: string;
  removeAlert: (id: string) => void;
};
export type SingleAlertComponentType = {
  dropItem: AlertItemType;
  removeAlert: (index: string) => void;
  navigateTo?: string;
  onClosePanel?: () => void;
  isSeen?: boolean;
};
export type AlertDropdownType = {
  children: JSX.Element;
  notificationRef?: React.RefObject<HTMLDivElement>;
  onClose?: () => void;
  serverNotifications?: Array<{
    id: string;
    title: string;
    link?: string | null;
    created_at?: string;
    is_read?: boolean;
  }>;
  markServerNotificationRead?: (id: string) => void;
  markAllServerNotificationsRead?: () => void;
};
export type AlertItemType = {
  type: "notice" | "error" | "success";
  title: string;
  link?: string;
  list?: Array<string>;
  id: string;
  created_at?: string;
};
