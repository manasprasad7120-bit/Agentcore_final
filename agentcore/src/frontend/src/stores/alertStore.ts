import { uniqueId } from "lodash";
import { create } from "zustand";
import type { AlertItemType } from "../types/alerts";
import type { AlertStoreType } from "../types/zustand/alert";
import { customStringify } from "../utils/reactFlowUtils";

const useAlertStore = create<AlertStoreType>((set, get) => ({
  errorData: { title: "", list: [] },
  noticeData: { title: "", link: "" },
  successData: { title: "" },
  notificationCenter: false,
  notificationList: [],
  tempNotificationList: [],
  addNotificationToHistory: (notification: Omit<AlertItemType, "id">) => {
    const newNotification = { ...notification, id: uniqueId(), created_at: new Date().toISOString() };
    set({
      notificationCenter: true,
      notificationList: [newNotification, ...get().notificationList],
    });
    // Persist every notification to DB so it survives page refresh.
    // Dynamic imports break the circular dep: api.tsx → useAlertStore → api.tsx
    const { title, link } = notification;
    Promise.all([
      import("../controllers/API/api.tsx"),
      import("../controllers/API/helpers/constants"),
    ])
      .then(([{ api }, { getURL }]) => {
        api
          .post(`${getURL("APPROVALS")}/notifications/general`, { title, link: link ?? null })
          .catch(() => {});
      })
      .catch(() => {});
  },
  addNotificationToTempList: (notification: Omit<AlertItemType, "id">) => {
    const newNotification = { ...notification, id: uniqueId() };
    const tempList = get().tempNotificationList;
    if (
      !tempList.some((item) => {
        return (
          customStringify({
            title: item.title,
            type: item.type,
            list: item.list,
            link: item.link,
          }) ===
          customStringify({
            title: newNotification.title,
            type: newNotification.type,
            list: newNotification.list,
            link: newNotification.link,
          })
        );
      })
    ) {
      set({
        tempNotificationList: [newNotification, ...get().tempNotificationList],
      });
    }
  },
  setErrorData: (newState: { title: string; list?: Array<string>; link?: string }) => {
    if (newState.title && newState.title !== "") {
      set({ errorData: newState });
      const notification: Omit<AlertItemType, "id"> = {
        type: "error",
        title: newState.title,
        list: newState.list,
        link: newState.link,
      };
      get().addNotificationToHistory(notification);
      get().addNotificationToTempList(notification);
    }
  },
  setNoticeData: (newState: { title: string; link?: string }) => {
    if (newState.title && newState.title !== "") {
      set({ noticeData: newState });
      const notification: Omit<AlertItemType, "id"> = {
        type: "notice",
        title: newState.title,
        link: newState.link,
      };
      get().addNotificationToHistory(notification);
      get().addNotificationToTempList(notification);
    }
  },
  setSuccessData: (newState: { title: string; link?: string }) => {
    if (newState.title && newState.title !== "") {
      set({ successData: { title: newState.title } });
      const notification: Omit<AlertItemType, "id"> = {
        type: "success",
        title: newState.title,
        link: newState.link,
      };
      get().addNotificationToHistory(notification);
      get().addNotificationToTempList(notification);
    }
  },
  setNotificationCenter: (newState: boolean) => {
    set({ notificationCenter: newState });
  },
  clearNotificationList: () => {
    set({ notificationList: [] });
  },
  removeFromNotificationList: (index: string) => {
    set({
      notificationList: get().notificationList.filter(
        (item) => item.id !== index,
      ),
    });
  },
  clearTempNotificationList: () => {
    set({ tempNotificationList: [] });
  },
  removeFromTempNotificationList: (index: string) => {
    set({
      tempNotificationList: get().tempNotificationList.filter(
        (item) => item.id !== index,
      ),
    });
  },
}));

export default useAlertStore;
