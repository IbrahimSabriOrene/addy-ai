import { Platform } from "react-native";
import Constants from "expo-constants";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { req } from "@/api/client";
import { translate } from "@/i18n";

const KEY = "addy:push-device";
export async function enableDeviceNotifications() {
  if (Platform.OS === "web") throw Error(translate("Browser notifications are not enabled. Your updates remain available in the app inbox."));
  const Notifications = await import("expo-notifications");
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) throw Error(translate("Device notifications are not available in this version. Your in-app preferences were saved."));
  if (Platform.OS === "android") await Notifications.setNotificationChannelAsync("campaigns", { name: translate("Campaign updates"), importance: Notifications.AndroidImportance.DEFAULT });
  const permission = await Notifications.requestPermissionsAsync();
  if (!permission.granted) throw Error(translate("Device notifications were not allowed. You can still use the inbox."));
  const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  await req("/v1/account/push-device", { method: "PUT", body: JSON.stringify({ token }) });
  await AsyncStorage.setItem(KEY, token);
}

export async function removeDeviceNotifications() {
  const token = await AsyncStorage.getItem(KEY);
  await clearLocalNotifications();
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 4000);
  try {
    if (token) await req("/v1/account/push-device", { method: "DELETE", body: JSON.stringify({ token }), signal: controller.signal });
  } finally { clearTimeout(timer); }
}

export async function clearLocalNotifications() {
  await AsyncStorage.removeItem(KEY);
  if (Platform.OS !== "web") {
    const n = await import("expo-notifications");
    await n.dismissAllNotificationsAsync().catch(() => {});
    await n.unregisterForNotificationsAsync().catch(() => {});
  }
}

export async function renewDeviceNotifications() {
  const token = await AsyncStorage.getItem(KEY);
  if (token && Platform.OS !== "web") {
    const n = await import("expo-notifications");
    if (!(await n.getPermissionsAsync()).granted) { await removeDeviceNotifications().catch(() => {}); return; }
    await req("/v1/account/push-device", { method: "PUT", body: JSON.stringify({ token }) }).catch(() => {});
  }
}
