import { Alert, Linking, Platform } from "react-native";
import { router } from "expo-router";
import { translate } from "@/i18n";

export const TERMS_URL = process.env.EXPO_PUBLIC_TERMS_URL ?? "";
export const PRIVACY_URL = process.env.EXPO_PUBLIC_PRIVACY_URL ?? "";
export const SUPPORT_URL = process.env.EXPO_PUBLIC_SUPPORT_URL ?? "";

export async function openPublicLink(value: string, name: string, allowEmail = false) {
  const draft = name === "Terms" ? "terms" : (name === "Privacy notice" || name === "Privacy policy") ? "privacy" : null;
  if (__DEV__ && !value && draft) {
    router.push({ pathname: "/legal-document", params: { document: draft } });
    return;
  }
  try {
    const url = new URL(value);
    if (url.username || url.password || !(url.protocol === "https:" || (allowEmail && url.protocol === "mailto:" && url.pathname))) {
      throw new Error("Unsupported public link");
    }
    await Linking.openURL(url.href);
  } catch {
    const message = translate(value ? "This link could not be opened. Please try again later." : "This preview has no published document or support contact yet. Nothing has been submitted.");
    const title = translate("{name} unavailable", { name: translate(name) });
    if (Platform.OS === "web") window.alert(`${title}\n\n${message}`);
    else Alert.alert(title, message);
  }
}
