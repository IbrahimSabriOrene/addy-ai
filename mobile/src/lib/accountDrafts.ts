import {clearLocalEdits} from "./localEdits";
import AsyncStorage from "@react-native-async-storage/async-storage";

let writes: Promise<void> = Promise.resolve();
const blockedPrefixes = new Set<string>();

/** Serialize creative writes so deletion drains in-flight writes before removing keys. */
export function writeAccountDraft(key: string, value: string): Promise<void> {
  const pending = writes.catch(() => {}).then(async () => {
    if ([...blockedPrefixes].some(prefix => key.startsWith(prefix))) {
      throw new Error("Draft saving stopped after account deletion was requested. Reopen the app if you abandoned deletion.");
    }
    await AsyncStorage.setItem(key, value);
  });
  writes = pending;
  return pending;
}

/** Remove creative drafts only; auth and purchase recovery have separate lifecycles. */
export async function clearAccountDrafts(email: string): Promise<void> {
  if (!email) throw new Error("Could not identify this account's drafts.");
  const api = process.env.EXPO_PUBLIC_API_URL;
  const prefixes = ["create", "campaign", "decision", "report", "pack-decision", "pack-command", "new-pack"]
    .map(kind => `addy:${kind}:${kind === "create" ? api ?? "demo" : api}:${email}:`);
  prefixes.forEach(prefix => blockedPrefixes.add(prefix));
  await writes.catch(() => {});
  await clearLocalEdits(email);
  const keys = (await AsyncStorage.getAllKeys()).filter(key => prefixes.some(prefix => key.startsWith(prefix)));
  if (keys.length) await AsyncStorage.multiRemove(keys);
}
