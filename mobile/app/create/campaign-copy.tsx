import { translate as tr, useI18n, Locale } from "@/i18n";
import React, { useEffect, useRef, useState } from "react";
import { TextInput, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { router, useLocalSearchParams } from "expo-router";
import { req } from "@/api/client";
import { writeAccountDraft } from "@/lib/accountDrafts";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { CampaignLanguage } from "@/components/CampaignLanguage";
import { ProductPreview } from "@/components/ProductPreview";
import { useTheme } from "@/theme/ThemeProvider";

type Brief = { campaignLanguage?: Locale; offer: string; caption: string; cta: string; instructions: string; color: string;
  font?: "sans" | "serif"; contact?: string; logoAssetKey?: string | null; style?: { id: string; version: number } };
type Source = { productId: string; imageVersion: number; assetKey: string; brief: Brief };
type Command = { key: string; body: Record<string, unknown>; result?: string };

export default function CopyCampaignScreen() {
  useI18n();
  const { campaign } = useLocalSearchParams<{ campaign: string }>(), t = useTheme();
  const [source, setSource] = useState<Source | null>(null), [brief, setBrief] = useState<Brief | null>(null);
  const [command, setCommand] = useState<Command | null>(null);
  const [busy, setBusy] = useState(true), [reviewed, setReviewed] = useState(false), [error, setError] = useState("");
  const storageKey = useRef(""), submitting = useRef(false);
  async function load() {
    setBusy(true); setError("");
    try {
      const account = await req<{ email: string }>("/v1/account");
      const key = `addy:campaign:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:copy:${campaign}`;
      const saved = await AsyncStorage.getItem(key);
      const pending: Command | null = saved ? JSON.parse(saved) : null;
      if (pending && (!pending.key || !pending.body?.productId || !Number.isInteger(pending.body.imageVersion))) throw Error(tr("Saved copy request could not be read."));
      storageKey.current = key; setCommand(pending);
      if (pending) return;
      const item = await req<Source>(`/v1/campaigns/${campaign}`);
      setSource(item); setBrief(item.brief); setReviewed(false);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load campaign.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [campaign]);
  async function duplicate() {
    if (busy || submitting.current || (!command && (!source || !brief || !reviewed))) return;
    submitting.current = true; setBusy(true); setError("");
    try {
      const { style, ...fields } = brief ?? {};
      const pending = command ?? { key: `copy-${Date.now()}-${Math.random().toString(36).slice(2)}`, body: {
        ...fields, productId: source!.productId, imageVersion: source!.imageVersion,
        ...(style ? { templateId: style.id, templateVersion: style.version } : {}),
      } };
      await writeAccountDraft(storageKey.current, JSON.stringify(pending)); setCommand(pending);
      const result = await req<{ id: string }>("/v1/campaigns", { method: "POST", headers: { "Idempotency-Key": pending.key }, body: JSON.stringify(pending.body) });
      if (!result.id) throw Error(tr("Copy response could not be confirmed. Retry the same request."));
      const completed = { ...pending, result: result.id };
      await writeAccountDraft(storageKey.current, JSON.stringify(completed)); setCommand(completed);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not copy campaign. Retry the same request.")); }
    finally { submitting.current = false; setBusy(false); }
  }
  return <Screen bottomInset={24}><TopBar title={tr("Duplicate campaign")} />
    <View style={{ gap: 12, marginTop: 16 }}>
      {command?.result ? <>
        <Text>{tr("Campaign copied without spending credits. Edit its layouts or review the price before generating a new pack.")}</Text>
        <Button label={tr("Open copied campaign")} onPress={() => router.push({ pathname: "/create/campaign-edit", params: { campaign: command.result! } })} />
        <Button label={tr("Prepare another copy")} variant="secondary" disabled={busy} onPress={() => {
          setBusy(true); void writeAccountDraft(storageKey.current, "null").then(load).catch(() => { setError(tr("Could not reset copy draft.")); setBusy(false); });
        }} />
      </> : <>
        {source && brief && !command && <>
          <ProductPreview assetKey={source.assetKey} />
          <CampaignLanguage value={brief.campaignLanguage} disabled={busy} onChange={campaignLanguage => { setBrief({ ...brief, campaignLanguage }); setReviewed(false); }} />
          <Text>{tr("Previous offer: {v0}", { v0: source.brief.offer || tr("No offer") })}</Text>
          <Text>{tr("This copies the saved image version, style and brand settings. Review old dates, prices and claims before saving.")}</Text>
          {([['offer', 'Offer for the new campaign', 300], ['caption', 'Caption', 2200], ['cta', 'Call to action', 100], ['instructions', 'Instructions', 500]] as const).map(([field, label, maxLength]) => <View key={field}>
            <Text>{tr(label)}</Text><TextInput accessibilityLabel={tr(label)} value={brief[field]} multiline maxLength={maxLength} editable={!busy}
              onChangeText={value => { setBrief({ ...brief, [field]: value }); setReviewed(false); }}
              style={{ color: t.colors.text, borderWidth: 1, borderColor: t.colors.borderStrong, padding: 12, minHeight: 44 }} />
          </View>)}
          <Button label={reviewed ? tr("Offer and dates reviewed") : tr("I reviewed the offer, dates and copy")} variant={reviewed ? "selected" : "secondary"} disabled={busy} onPress={() => setReviewed(!reviewed)} />
        </>}
        {!!command && <Text>{tr("Saved copy request. Retrying reuses the same details and cannot create a second campaign.")}</Text>}
        <Button label={command ? tr("Retry same copy") : tr("Save campaign copy · no credits")} disabled={busy || (!command && !reviewed)} loading={busy} onPress={() => void duplicate()} />
      </>}
      {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
      {!command && !source && <Button label={tr("Reload source campaign")} disabled={busy} onPress={() => void load()} />}
    </View>
  </Screen>;
}
