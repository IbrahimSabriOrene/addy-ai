import React, { useEffect } from "react";
import { AppState, Platform } from "react-native";
import { router, usePathname } from "expo-router";
import { trackEngagement } from "@/lib/engagement";
import { renewDeviceNotifications } from "@/lib/notifications";
import { USE_MOCK } from "@/api/client";

export function EngagementBridge() {
  const path = usePathname();
  useEffect(() => {
    const event = path.includes("result") ? "result" : path.includes("customize") || path === "/create/campaign" ? "customize" : path.includes("browse") ? "browse" : null;
    if (event) void trackEngagement(event);
  }, [path]);
  useEffect(() => {
    if (USE_MOCK || Platform.OS === "web") return;
    let disposed = false, subscription: { remove(): void } | undefined;
    void renewDeviceNotifications();
    const state = AppState.addEventListener("change", value => { if (value === "active") void renewDeviceNotifications(); });
    void import("expo-notifications").then(async n => {
      if (disposed) return;
      const open = (response: import("expo-notifications").NotificationResponse) => {
        if (response.notification.request.content.data?.screen === "notifications") router.push("/notifications");
      };
      subscription = n.addNotificationResponseReceivedListener(open);
      const previous = await n.getLastNotificationResponseAsync();
      if (!disposed && previous) { open(previous); await n.clearLastNotificationResponseAsync(); }
    }).catch(() => {});
    return () => { disposed = true; subscription?.remove(); state.remove(); };
  }, []);
  return null;
}
