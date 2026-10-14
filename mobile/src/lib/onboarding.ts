import * as SecureStore from "expo-secure-store";

const KEY = "mam.onboarded";

export async function hasOnboarded(): Promise<boolean> {
  try {
    return (await SecureStore.getItemAsync(KEY)) === "1";
  } catch {
    return false;
  }
}

export async function markOnboarded(): Promise<void> {
  await SecureStore.setItemAsync(KEY, "1").catch(() => {});
}
