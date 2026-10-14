import { useI18n, translate as tr } from "@/i18n";
import React, { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/Button";
import { Text } from "@/components/Text";
import { AuthError, req, USE_MOCK } from "@/api/client";
import { draftReturn } from "@/lib/draftReturn";

type Eligibility = { confirmed: boolean; policyVersion: string; statement: string; confirmedAt: string | null };

export default function AgeCheckScreen() {
  const { locale } = useI18n();
  const router = useRouter();
  const { returnTo } = useLocalSearchParams<{ returnTo?: string }>();
  const [policy, setPolicy] = useState<Eligibility | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsSignIn, setNeedsSignIn] = useState(false);
  async function load() {
    setBusy(true); setError(""); setNeedsSignIn(false);
    try {
      setPolicy(USE_MOCK
        ? { confirmed: false, policyVersion: "demo", statement: tr("I am 18 or older and will use Addy AI for professional or business purposes."), confirmedAt: null }
        : await req<Eligibility>("/v1/account/eligibility"));
    } catch (e) { setNeedsSignIn(e instanceof AuthError); setError(e instanceof Error ? e.message : tr("Could not check eligibility.")); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!policy || !checked || busy) return;
    setBusy(true); setError("");
    try {
      if (!USE_MOCK) await req("/v1/account/eligibility", { method: "POST", body: JSON.stringify({ over18: true, businessUse: true, policyVersion: policy.policyVersion }) });
      router.replace(draftReturn(returnTo) ?? "/home");
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not save confirmation. Reload and try again.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  return <Screen bottomInset={24}>
    <TopBar title={tr("Age eligibility")} fallbackHref="/account" />
    <View style={{ gap: 18, paddingVertical: 24 }}>
      <Text variant="subheading">{tr("For adults and professional use")}</Text>
      <Text>{tr("Addy AI is available only to people aged 18 or older for professional or business purposes. If you are under 18, do not upload photos or use generation.")}</Text>
      <Text>{tr("We record your confirmation and its date, not your birth date or an identity document. This is separate from permission to send media to AI services.")}</Text>
      {USE_MOCK && <Text>{tr("This preview does not save an account confirmation.")}</Text>}
      {policy?.confirmed ? <>
        <Text accessibilityLiveRegion="polite">{tr("Your confirmation is recorded.")}</Text>
        <Button label="Continue" onPress={() => router.replace(draftReturn(returnTo) ?? "/home")} />
      </> : <>
        {policy && <Pressable accessibilityRole="checkbox" accessibilityLabel={tr(policy.statement)} accessibilityState={{ checked, disabled: busy }} aria-checked={checked} disabled={busy} onPress={() => setChecked(!checked)} style={{ minHeight: 48, paddingVertical: 12 }}>
          <Text>{checked ? "☑" : "☐"} {tr(policy.statement)}</Text>
        </Pressable>}
        <Button label={tr("Confirm and continue")} disabled={!policy || !checked || busy} loading={busy} onPress={() => void confirm()} />
      </>}
      {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
      {needsSignIn && <Button label="Sign in" onPress={() => router.push("/sign-in")} />}
      <Button label={tr("Reload eligibility")} variant="ghost" loading={busy} onPress={() => void load()} />
      <Button label={tr("Privacy & legal")} variant="secondary" onPress={() => router.push("/privacy-legal")} />
      <Button label={tr("Leave this screen")} variant="ghost" onPress={() => router.replace("/account")} />
    </View>
  </Screen>;
}
