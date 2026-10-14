import { ColorField } from "@/components/ColorField";
import { translate as tr, useI18n, Locale } from "@/i18n";
import React, { useEffect, useState } from "react";
import { View, TextInput } from "react-native";
import * as Clipboard from "expo-clipboard";
import { req, ApiError } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { ProductPreview } from "./ProductPreview";
import { CampaignLayouts } from "./CampaignLayouts";
import { CampaignLogo } from "./CampaignLogo";
import { CampaignPackHistory } from "./CampaignPackHistory";
import { GenerateCampaign } from "./GenerateCampaign";
import { useTheme } from "@/theme/ThemeProvider";
import { router } from "expo-router";
import { BrandStyle, BrandFields, ApplyBrand } from "./BrandFields";
import { CampaignPlanner, Objective } from "./CampaignPlanner";

type Brief = BrandStyle & { campaignLanguage?: Locale; objective?: Objective; offer: string; caption: string; cta: string; color: string; instructions: string; logoAssetKey?: string | null };
type Campaign = { id: string; version: number; imageVersion: number; assetKey: string; brief: Brief };
type Page = { items: (Campaign & { createdAt: string })[]; nextCursor: string | null };

export function CampaignDetails({ id }: { id: string }) {
  const { locale } = useI18n();
  const t = useTheme();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [notice, setNotice] = useState("");

  async function load() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await req<Campaign>(`/v1/campaigns/${id}`);
      setCampaign(result); setBrief(result.brief); setStale(false);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load campaign.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [id]);

  async function save() {
    if (!campaign || !brief || busy || stale) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const { offer, caption, cta, color, logoAssetKey, font, contact, objective, campaignLanguage } = brief;
      const result = await req<Pick<Campaign, "version" | "brief">>(`/v1/campaigns/${id}`, {
        method: "PATCH", body: JSON.stringify({ expectedVersion: campaign.version, offer, caption, cta, color, logoAssetKey, font, contact, objective, campaignLanguage }),
      });
      setCampaign({ ...campaign, ...result }); setBrief(result.brief);
      setNotice(tr("Campaign saved. Prepare the layouts to apply your changes."));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStale(true);
      setError(e instanceof Error ? e.message : tr("Could not save campaign."));
    } finally { setBusy(false); }
  }

  async function copy() {
    if (!brief) return;
    try { await Clipboard.setStringAsync([brief.caption, brief.cta].filter(Boolean).join("\n")); setNotice(tr("Caption and CTA copied.")); }
    catch { setError(tr("Could not copy text.")); }
  }

  return <View style={{ gap: 12 }}>
    {!!campaign && !!brief && <>
      <Text>{tr("Approved product photo · version {v0}", { v0: campaign.imageVersion })}</Text>
      <ProductPreview assetKey={campaign.assetKey} />
      <CampaignPlanner brief={brief} assetKey={campaign.assetKey} disabled={busy || stale} onChange={patch => setBrief({ ...brief, ...patch })} />
      <Button label={tr("Duplicate campaign")} variant="secondary" disabled={busy || stale || JSON.stringify(brief) !== JSON.stringify(campaign.brief)}
        onPress={() => router.push({ pathname: "/create/campaign-copy", params: { campaign: id } })} />
      <ApplyBrand disabled={busy || stale} onApply={({ color, font, contact, logoAssetKey }) => setBrief(current => current ? { ...current, color, font, contact, logoAssetKey } : current)} />
      <BrandFields value={brief} disabled={busy || stale} onChange={patch => setBrief(current => current ? { ...current, ...patch } : current)} />
      {([['offer', 'Offer', 300], ['caption', 'Caption', 2200], ['cta', 'Call to action', 100], ['color', 'Background color (#RRGGBB)', 7]] as const).map(([field, label, maxLength]) => field === "color" ? <ColorField key={field} label={tr(label)} value={brief[field]} disabled={busy || stale} onChange={value => setBrief({ ...brief, color: value })} /> : <View key={field}>
        <Text>{tr(label)}</Text>
        <TextInput accessibilityLabel={tr(label)} value={brief[field]} maxLength={maxLength} multiline
          editable={!busy && !stale} autoCorrect autoCapitalize="sentences"
          onChangeText={value => setBrief({ ...brief, [field]: value })}
          style={{ color: t.colors.text, borderWidth: 1, borderColor: t.colors.borderStrong, padding: 12, minHeight: 44, borderRadius: 12 }} />
      </View>)}
      {!/^#[0-9a-fA-F]{6}$/.test(brief.color) && <Text accessibilityRole="alert">{tr("Enter a background color as # followed by six hexadecimal characters, for example #12ABEF.")}</Text>}
      <CampaignLogo assetKey={brief.logoAssetKey} disabled={busy || stale} onBusyChange={setBusy}
        onChange={logoAssetKey => setBrief(current => current ? { ...current, logoAssetKey } : current)} />
      <Text>{tr("Saving text or a logo does not generate media or spend credits.")}</Text>
      <Button label={tr("Save campaign text")} loading={busy} disabled={busy || stale || !/^#[0-9a-fA-F]{6}$/.test(brief.color)} onPress={() => void save()} />
      <Button label={tr("Copy caption and CTA")} variant="secondary" disabled={busy || stale} onPress={() => void copy()} />
      <CampaignLayouts key={`${id}-${campaign.version}`} campaignId={id} version={campaign.version}
        disabled={busy || stale || JSON.stringify(brief) !== JSON.stringify(campaign.brief)} />
      <CampaignPackHistory key={`pack-${id}-${campaign.version}`} campaignId={id} currentVersion={campaign.version} />
      <GenerateCampaign key={`generate-${id}-${campaign.version}`} campaignId={id} version={campaign.version}
        disabled={busy || stale || JSON.stringify(brief) !== JSON.stringify(campaign.brief)} />
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{tr(notice)}</Text>}
    {(!campaign || stale) && <Button label={stale ? tr("Reload campaign and discard local edits") : tr("Reload campaign")} disabled={busy} loading={busy} onPress={() => void load()} />}
  </View>;
}

export function ProductCampaigns({ productId }: { productId: string }) {
  const { locale } = useI18n();
  const [items, setItems] = useState<Page["items"]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  async function load(next?: string) {
    setBusy(true); setError("");
    try {
      const page = await req<Page>(`/v1/products/${productId}/campaigns${next ? `?cursor=${encodeURIComponent(next)}` : ""}`);
      setItems(previous => next ? [...previous, ...page.items.filter(item => !previous.some(old => old.id === item.id))] : page.items);
      setCursor(page.nextCursor); setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load campaigns.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [productId]);
  return <View style={{ gap: 12 }}>
    <Text>{tr("Campaign history")}</Text>
    <Button label={tr("Refresh campaign history")} variant="ghost" disabled={busy} loading={busy} onPress={() => void load()} />
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {loaded && !items.length && <Text>{tr("No campaigns saved for this product yet.")}</Text>}
    {items.map(item => <View key={item.id} style={{ gap: 12 }}>
      <Text>{new Date(item.createdAt).toLocaleDateString(locale)} · {item.brief.offer || tr("No offer")}</Text>
      <Button label={selected === item.id ? tr("Close campaign") : tr("View campaign")} variant="secondary" onPress={() => setSelected(selected === item.id ? null : item.id)} />
      {selected === item.id && <CampaignDetails key={item.id} id={item.id} />}
    </View>)}
    {!!cursor && <Button label={tr("Load more campaigns")} disabled={busy} loading={busy} onPress={() => void load(cursor)} />}
  </View>;
}
