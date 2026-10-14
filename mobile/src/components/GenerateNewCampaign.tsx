import { translate as tr, useI18n, Locale } from "@/i18n";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import { Modal, ScrollView, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";
import { req } from "@/api/client";
import { useTheme } from "@/theme/ThemeProvider";
import { Button } from "./Button";
import { Text } from "./Text";
import { ResumeSignIn } from "./ResumeSignIn";

type Body = { campaignLanguage?: Locale; productId: string; imageVersion: number; templateId: string; templateVersion: number;
  offer: string; instructions: string; caption: string; cta: string; color: string };
type Result = { id: string; campaignId: string; campaignVersion: number };
type Command = { key: string; body: Body & { confirmedCredits: number }; result?: Result };
type Quote = { available: boolean; priceCredits: number | null; scope: string; settlement: string };
type Consent = { granted: boolean; disclosureVersion: string; disclosure: string };

export function GenerateNewCampaign({ product, template, body, disabled, onLockedChange, onStartNew }: {
  product: string; template: string; body: Body | null; disabled: boolean; onLockedChange: (value: boolean) => void;
  onStartNew: () => Promise<void>;
}) {
  useI18n();
  const router = useRouter(), t = useTheme();
  const storageKey = useRef("");
  const [command, setCommand] = useState<Command | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [details, setDetails] = useState(false);
  useEffect(() => { onLockedChange(busy || !!command); }, [busy, command, onLockedChange]);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(""); storageKey.current = "";
    void (async () => {
      try {
        const account = await req<{ email: string }>("/v1/account");
        const key = `addy:new-pack:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${product}:${template}`;
        const saved = await AsyncStorage.getItem(key);
        const pending: Command | null = saved ? JSON.parse(saved) : null;
        if (pending && (typeof pending.key !== "string" || !pending.key || pending.body?.productId !== product || pending.body.templateId !== template
          || !Number.isInteger(pending.body.confirmedCredits) || pending.body.confirmedCredits < 1 || pending.body.confirmedCredits > 10000)) throw Error(tr("Saved generation could not be read."));
        const currentQuote = pending ? null : await req<Quote>("/v1/campaign-pack/quote");
        if (currentQuote && (currentQuote.scope !== "campaign_pack" || (currentQuote.available && (!Number.isInteger(currentQuote.priceCredits) || currentQuote.priceCredits! < 1 || currentQuote.priceCredits! > 10000)))) throw Error(tr("Pack price could not be confirmed."));
        if (active) { storageKey.current = key; setCommand(pending); setQuote(currentQuote); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : tr("Could not load pack price.")); }
      finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, [product, template, reload]);

  async function accepted(pending: Command, result: Result) {
    if (!result.id || !result.campaignId || !Number.isInteger(result.campaignVersion) || result.campaignVersion < 1) throw Error(tr("Generation response could not be confirmed. Retry the same request."));
    const saved = { ...pending, result };
    await writeAccountDraft(storageKey.current, JSON.stringify(saved));
    setCommand(saved);
    router.push({ pathname: "/create/campaign-result", params: { campaign: result.campaignId, version: String(result.campaignVersion) } });
  }
  async function generate(allow = false) {
    if (busy || !storageKey.current || (!command && (disabled || !body || !quote?.available))) return;
    setBusy(true); setError("");
    try {
      if (command?.result) { await accepted(command, command.result); return; }
      if (!command) {
        if (allow && consent) await req("/v1/account/ai-consent", { method: "PUT", body: JSON.stringify({ granted: true, disclosureVersion: consent.disclosureVersion }) });
        const permission = await req<Consent>("/v1/account/ai-consent");
        if (!permission.granted) { setConsent(permission); return; }
      }
      setConsent(null);
      const pending = command ?? { key: `new-pack-${Date.now()}-${Math.random().toString(36).slice(2)}`, body: { ...body!, confirmedCredits: quote!.priceCredits! } };
      setCommand(pending);
      await writeAccountDraft(storageKey.current, JSON.stringify(pending));
      await accepted(pending, await req<Result>("/v1/campaign-pack/generate", { method: "POST", headers: { "Idempotency-Key": pending.key }, body: JSON.stringify(pending.body) }));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not start generation. Retry the saved request.")); }
    finally { setBusy(false); }
  }
  async function close() {
    if (busy || !command || command.result) return;
    setBusy(true); setError("");
    try {
      const result = await req<Result & { state: string }>("/v1/campaign-pack/generate/close", { method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body) });
      if (result.id) await accepted(command, result);
      else if (result.state === "cancelled") {
        await AsyncStorage.removeItem(storageKey.current); setCommand(null); setQuote(null); setReload(value => value + 1);
      } else throw Error(tr("The saved request could not be resolved."));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not check the saved request.")); }
    finally { setBusy(false); }
  }
  async function startNew() {
    if (busy || !command?.result) return;
    setBusy(true); setError("");
    try {
      // Clear the offer first: a storage failure must not silently reuse an old offer.
      await onStartNew();
      await AsyncStorage.removeItem(storageKey.current);
      setCommand(null); setQuote(null); setReload(value => value + 1);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not start another campaign.")); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 8 }}>
    <Button label={tr("Pack & credit details")} variant="ghost" onPress={() => setDetails(true)} />
    {details && <Modal visible transparent animationType="slide" onRequestClose={() => setDetails(false)}>
      <View accessibilityViewIsModal style={{ flex: 1, justifyContent: "center", padding: 20, backgroundColor: "rgba(0,0,0,0.75)" }}>
        <ScrollView style={{ maxHeight: "90%", backgroundColor: t.colors.bg, borderRadius: 16 }} contentContainerStyle={{ padding: 20, gap: 16 }}>
          <Text variant="heading">{tr("Pack & credit details")}</Text>
          <Text>{tr("Campaign pack · product image, video, story, feed and caption/CTA")}</Text>
          <Text>{tr("Credits are reserved now; incomplete work may remain held for review. Spent on delivery or acceptance.")}</Text>
          {!!quote?.settlement && <Text>{tr(quote.settlement)}</Text>}
          <Button label={tr("Close")} onPress={() => setDetails(false)} />
        </ScrollView>
      </View>
    </Modal>}
    {!!command && !command.result && <Button label={tr("Check saved request before starting over")} variant="secondary" disabled={busy} onPress={() => void close()} />}
    {!!command && !command.result && <Button label={tr("Check balance and get credits")} variant="secondary" disabled={busy}
      onPress={() => router.push({ pathname: "/paywall", params: { returnTo: `/create/campaign?${new URLSearchParams({ product, template })}` } })} />}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    <ResumeSignIn error={error} returnTo={`/create/campaign?${new URLSearchParams({ product, template })}`} />
    {!command && !quote?.available && !busy && <Text>{tr("Campaign generation is unavailable. Your draft is retained.")}</Text>}
    <Button label={command?.result ? tr("View generated campaign") : command ? tr("Retry saved generation · {credits} credits", { credits: command.body.confirmedCredits }) : tr("Generate · {credits} credits", { credits: quote?.priceCredits ?? "—" })}
      loading={busy} disabled={busy || !!consent || (!command && (disabled || !body || !quote?.available))} onPress={() => void generate()} />
    {!!command?.result && <Button label={tr("Start another campaign")} variant="secondary" disabled={busy} onPress={() => void startNew()} />}
    {!!error && !command && <Button label={tr("Reload pack price")} variant="ghost" disabled={busy} onPress={() => setReload(value => value + 1)} />}
    {!!consent && <Modal visible transparent animationType="slide" onRequestClose={() => setConsent(null)}>
      <View accessibilityViewIsModal style={{ flex: 1, justifyContent: "center", padding: 20, backgroundColor: "rgba(0,0,0,0.75)" }}>
        <ScrollView style={{ maxHeight: "90%", backgroundColor: t.colors.bg, borderRadius: 16 }} contentContainerStyle={{ padding: 20, gap: 14 }}>
          <Text variant="heading">{tr("Create with Addy AI")}</Text><Text>{tr(consent.disclosure)}</Text>
          <Text>{tr(quote?.settlement ?? "")}</Text>
          {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
          <Button label={tr("Allow AI processing and generate")} disabled={busy} onPress={() => void generate(true)} />
          <Button label={tr("Do not allow")} variant="secondary" disabled={busy} onPress={() => setConsent(null)} />
        </ScrollView>
      </View>
    </Modal>}
  </View>;
}
