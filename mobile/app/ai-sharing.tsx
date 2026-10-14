import { useI18n, translate as tr } from "@/i18n";
import { DemoSharing } from "@/components/DemoControls";
import React, { useEffect, useState } from "react";
import { View } from "react-native";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { req, USE_MOCK } from "@/api/client";

type Consent = { granted: boolean; disclosureVersion: string; disclosure: string };

export default function AISharingScreen() {
  const { locale } = useI18n();
  const [consent, setConsent] = useState<Consent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    if (USE_MOCK) return;
    setBusy(true);
    setError("");
    try { setConsent(await req<Consent>("/v1/account/ai-consent")); }
    catch (e) { setError(e instanceof Error ? e.message : tr("Could not load permission.")); }
    finally { setBusy(false); }
  }

  async function update(granted: boolean) {
    if (!consent) return;
    setBusy(true);
    setError("");
    try {
      const saved = await req<Pick<Consent, "granted" | "disclosureVersion">>("/v1/account/ai-consent", {
        method: "PUT", body: JSON.stringify({ granted, disclosureVersion: consent.disclosureVersion }),
      });
      setConsent({ ...consent, ...saved });
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not update permission.")); }
    finally { setBusy(false); }
  }

  useEffect(() => { void load(); }, []);
  if (USE_MOCK) return <DemoSharing />;
  return <Screen bottomInset={24}>
    <TopBar title={tr("AI sharing")} />
    <View style={{ gap: 20, paddingVertical: 20 }}>
      {USE_MOCK ? <Text>{tr("Connect and sign in to manage your account's AI-sharing permission.")}</Text> : <>
        {consent && <>
          <Text>{tr(consent.disclosure)}</Text>
          <Text accessibilityLiveRegion="polite">{consent.granted ? tr("Permission granted") : tr("Permission not granted")}</Text>
          <Text>{tr("Photo-library access is separate from this permission.")}</Text>
          {!consent.granted && <Button label={tr("Allow AI processing")} disabled={busy} onPress={() => void update(true)} />}
          <Button label={consent.granted ? tr("Withdraw permission") : tr("Do not allow")} variant="secondary" disabled={busy} onPress={() => void update(false)} />
        </>}
        {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
        <Button label={tr("Refresh permission")} variant="ghost" loading={busy} onPress={() => void load()} />
      </>}
    </View>
  </Screen>;
}
