/**
 * Auth token management — stores/retrieves the JWT in expo-secure-store and
 * provides helpers the API client uses to attach Authorization headers and
 * handle 401 refresh cycles.
 *
 * Sign-in-with-Apple and the actual /auth endpoint are wired separately (in
 * the auth screen); this module is the low-level plumbing they both depend on.
 */
import * as SecureStore from "expo-secure-store";
import { supabase } from "./supabase";

const TOKEN_KEY = "mam.auth.token";
const REFRESH_KEY = "mam.auth.refresh";

let cachedToken: string | null = null;

export async function getToken(): Promise<string | null> {
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? null;
  }
  if (cachedToken) return cachedToken;
  try {
    cachedToken = await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    cachedToken = null;
  }
  return cachedToken;
}

export async function setTokens(token: string, refresh?: string): Promise<void> {
  cachedToken = token;
  await SecureStore.setItemAsync(TOKEN_KEY, token).catch(() => {});
  if (refresh) {
    await SecureStore.setItemAsync(REFRESH_KEY, refresh).catch(() => {});
  }
}

export async function getRefreshToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(REFRESH_KEY);
  } catch {
    return null;
  }
}

export async function refreshAccessToken(): Promise<boolean> {
  if (!supabase) return false;
  const { data, error } = await supabase.auth.refreshSession();
  cachedToken = error ? null : data.session?.access_token ?? null;
  return !!cachedToken;
}

export async function clearTokens(): Promise<void> {
  cachedToken = null;
  await SecureStore.deleteItemAsync(TOKEN_KEY).catch(() => {});
  await SecureStore.deleteItemAsync(REFRESH_KEY).catch(() => {});
  if (supabase) {
    const { error } = await supabase.auth.signOut({ scope: "local" });
    if (error && (await supabase.auth.getSession()).data.session) throw error;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  return !!(await getToken());
}
