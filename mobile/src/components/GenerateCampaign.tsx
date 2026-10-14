import { translate as tr, useI18n } from "@/i18n";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import { View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";

type Quote = { campaignVersion: number; available: boolean; priceCredits: number | null; settlement: string };
type Consent = { granted: boolean; disclosureVersion: string; disclosure: string };
type Command = { key: string; body: { expectedVersion: number; confirmedCredits: number }; jobId?: string };

export function GenerateCampaign({ campaignId, version, disabled }: { campaignId: string; version: number; disabled: boolean }) {
  useI18n();
  const router = useRouter();
  const storageKey = useRef("");
  const [command, setCommand] = useState<Command | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setBusy(true); setError("");
    void (async () => {
      try {
        const account = await req<{ email: string }>("/v1/account");
        const key = `addy:pack-command:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${campaignId}:${version}`;
        const saved = await AsyncStorage.getItem(key);
        const restored: Command | null = saved ? JSON.parse(saved) : null;
        if (restored && (typeof restored.key !== "string" || restored.body?.expectedVersion !== version || !Number.isInteger(restored.body.confirmedCredits) || restored.body.confirmedCredits < 1)) throw Error(tr("Saved generation could not be read."));
        const currentQuote = restored ? null : await req<Quote>(`/v1/campaigns/${campaignId}/generation-quote`);
        if (currentQuote && currentQuote.campaignVersion !== version) throw Error(tr("Campaign changed. Reload the campaign before generating."));
        if (active) { storageKey.current = key; setCommand(restored); setQuote(currentQuote); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : tr("Could not load generation details.")); }
      finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, [campaignId, version, reload]);
  function openResult(value: Command) {
    router.push({ pathname: "/create/campaign-result", params: { campaign: campaignId, version: String(value.body.expectedVersion) } });
  }
  async function closeUnaccepted() {
    if (busy || !command || command.jobId) return;
    setBusy(true); setError("");
    try {
      const result = await req<{ id?: string; state: string }>(`/v1/campaigns/${campaignId}/generate/close`, {
        method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body),
      });
      if (result.id) {
        const accepted = { ...command, jobId: result.id };
        await writeAccountDraft(storageKey.current, JSON.stringify(accepted));
        setCommand(accepted); openResult(accepted);
      } else if (result.state === "cancelled") {
        await AsyncStorage.removeItem(storageKey.current);
        setCommand(null); setQuote(null); setConsent(null); setReload(value => value + 1);
      } else throw Error(tr("The saved request could not be resolved. Retry the check."));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not check the saved request.")); }
    finally { setBusy(false); }
  }
  async function generate(allow = false) {
    if (busy || !storageKey.current || (!command && (disabled || !quote?.available || !quote.priceCredits))) return;
    if (command?.jobId) { openResult(command); return; }
    setBusy(true); setError("");
    try {
      if (!command) {
        if (allow && consent) await req("/v1/account/ai-consent", { method: "PUT", body: JSON.stringify({ granted: true, disclosureVersion: consent.disclosureVersion }) });
        const permission = await req<Consent>("/v1/account/ai-consent");
        if (!permission.granted) { setConsent(permission); return; }
      }
      setConsent(null);
      const pending = command ?? { key: `pack-${Date.now()}-${Math.random().toString(36).slice(2)}`, body: { expectedVersion: version, confirmedCredits: quote!.priceCredits! } };
      setCommand(pending);
      await writeAccountDraft(storageKey.current, JSON.stringify(pending));
      const result = await req<{ id: string }>(`/v1/campaigns/${campaignId}/generate`, { method: "POST", headers: { "Idempotency-Key": pending.key }, body: JSON.stringify(pending.body) });
      const accepted = { ...pending, jobId: result.id };
      await writeAccountDraft(storageKey.current, JSON.stringify(accepted));
      setCommand(accepted); openResult(accepted);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not start generation. Retry the same request.")); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 12 }}>
    <Text>{tr("Generate campaign pack")}</Text>
    <Text>{tr("Approved product image, video with sound, story, feed image, caption and CTA.")}</Text>
    {!!quote && <Text>{quote.available ? tr("{credits} credits · {settlement}", { credits: quote.priceCredits ?? "—", settlement: tr(quote.settlement) }) : tr("Campaign generation is not available yet.")}</Text>}
    {disabled && !command && <Text>{tr("Save your campaign changes before generating.")}</Text>}
    {!!command && !command.jobId && <Text>{tr("Retrying the saved request for version {v0} · {v1} credits.", { v0: command.body.expectedVersion, v1: command.body.confirmedCredits })}</Text>}
    {!!command && !command.jobId && <>
      <Text>{tr("Check before starting over: an accepted request opens its existing result. An unaccepted request is closed so you can review the current price again.")}</Text>
      <Button label={tr("Check saved request before starting over")} variant="secondary" disabled={busy} onPress={() => void closeUnaccepted()} />
    </>}
    {!!consent && <>
      <Text>{tr(consent.disclosure)}</Text>
      <Button label={tr("Allow AI processing and generate")} disabled={busy || disabled} onPress={() => void generate(true)} />
      <Button label={tr("Do not allow")} variant="secondary" disabled={busy} onPress={() => { setConsent(null); setError(tr("AI processing was not allowed. Your campaign is saved.")); }} />
    </>}
    {!consent && <Button label={command?.jobId ? tr("View generated campaign") : command ? tr("Retry saved generation") : quote?.priceCredits ? tr("Generate pack · {credits} credits", { credits: quote.priceCredits }) : tr("Generate pack")} loading={busy}
      disabled={busy || (!command && (disabled || !quote?.available))} onPress={() => void generate()} />}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    <Button label={tr("Reload generation details")} variant="ghost" disabled={busy} onPress={() => setReload(value => value + 1)} />
  </View>;
}
