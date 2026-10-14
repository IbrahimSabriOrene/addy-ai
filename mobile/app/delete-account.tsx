import { useI18n } from "@/i18n";
import React, { useState } from "react";
import { TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { ApiError, req, USE_MOCK } from "@/api/client";
import { clearTokens } from "@/lib/auth";
import { clearAccountDrafts } from "@/lib/accountDrafts";
import { useTheme } from "@/theme/ThemeProvider";

export default function DeleteAccountScreen() {
  const { tr } = useI18n();
  const theme = useTheme();
  const router = useRouter();
  const queries = useQueryClient();
  const [confirmation, setConfirmation] = useState("");
  const [state, setState] = useState<"requested" | "completed" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (busy || confirmation !== "DELETE" || state) return;
    if (USE_MOCK) { setError("Demo only: there is no real account to delete. Use Sign out in Account to leave the preview."); return; }
    setBusy(true); setError("");
    try {
      let account: { email: string } | null = null;
      try { account = await req<{ email: string }>("/v1/account"); }
      catch (e) {
        // An accepted deletion disables /account; preserve idempotent deletion replay.
        if (!(e instanceof ApiError) || e.status !== 410) throw e;
      }
      if (account) await clearAccountDrafts(account.email);
      const result = await req<{ state: string }>("/v1/account/deletion", { method: "POST", body: JSON.stringify({ confirmation: "DELETE" }) });
      if (result.state !== "requested" && result.state !== "completed") throw Error("The deletion status could not be confirmed. Retry the same request.");
      setState(result.state);
      await queries.cancelQueries();
      queries.clear();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not confirm the request. You can safely retry."); }
    finally { setBusy(false); }
  }
  async function signOut() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await clearTokens();
      queries.clear();
      router.replace("/sign-in");
    } catch { setError("Could not finish signing out. Retry sign-out; your deletion request remains recorded."); }
    finally { setBusy(false); }
  }
  return <Screen bottomInset={24}>
    <TopBar title={tr('Delete account')} />
    <View style={{ gap: 16, marginTop: 20 }}>
      {state ? <>
        <Text accessibilityLiveRegion="polite">{tr(state === "completed" ? "Account deletion completed." : "Deletion requested. Access to your account is disabled. Data cleanup is still pending.")}</Text>
        <Button label={tr('Sign out of this device')} disabled={busy} loading={busy} onPress={() => void signOut()} />
      </> : <>
        <Text>{tr('Request deletion of your account, saved products, campaigns and media. Account access stops when the request is accepted, and pending generations are closed.')}</Text>
        <Text>{tr('Data cleanup is a separate step and is not immediate. Financial records and backup copies require separate retention handling. A request cannot undo data already sent for AI processing.')}</Text>
        <Text>{tr('Submitting first removes this account’s local creative drafts and pending creative commands on this device, even if the server request later fails. Purchase recovery records are retained.')}</Text>
        <Text>{tr('Type DELETE to confirm. If the response is lost, you can safely send this request again.')}</Text>
        <TextInput accessibilityLabel={tr('Deletion confirmation')} value={confirmation} onChangeText={setConfirmation} editable={!busy}
          autoCapitalize="characters" autoCorrect={false} maxLength={6}
          style={{ color: theme.colors.text, borderColor: theme.colors.borderStrong, borderWidth: 1, padding: 12 }} />
        <Button label={tr('Request account deletion')} variant="danger" disabled={busy || confirmation !== "DELETE"} loading={busy} onPress={() => void submit()} />
        <Button label={tr('Keep my account')} variant="secondary" disabled={busy} onPress={() => router.canGoBack() ? router.back() : router.replace("/account")} />
      </>}
      {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    </View>
  </Screen>;
}
