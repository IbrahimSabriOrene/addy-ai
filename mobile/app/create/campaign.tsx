import { ColorField } from "@/components/ColorField";
import { translate as tr, useI18n, Locale } from "@/i18n";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useLocalSearchParams } from "expo-router";
import { req } from "@/api/client";
import { getCatalogue, templatePreview } from "@/api/creation";
import { GenerateNewCampaign } from "@/components/GenerateNewCampaign";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/Button";
import { Text } from "@/components/Text";
import { ProductPreview } from "@/components/ProductPreview";
import { StylePreview } from "@/components/StylePreview";
import { CampaignDetails } from "@/components/ProductCampaigns";
import { CampaignLogo } from "@/components/CampaignLogo";
import { BrandStyle, BrandFields, ApplyBrand } from "@/components/BrandFields";
import { useTheme } from "@/theme/ThemeProvider";
import { CampaignPlanner, Objective } from "@/components/CampaignPlanner";

type Brief = BrandStyle & { campaignLanguage?: Locale; objective?: Objective; offer: string; instructions: string; caption: string; cta: string; color: string; logoAssetKey?: string | null };
type Draft = { brief: Brief; command?: { key: string; previewUri?: string | null; body: Brief & { productId: string; imageVersion: number; templateId: string; templateVersion: number } }; campaignId?: string };
const EMPTY: Draft = { brief: { offer: "", instructions: "", caption: "", cta: "", color: "#FFFFFF" } };

export default function CampaignCustomizeScreen() {
  useI18n();
  const { product, template } = useLocalSearchParams<{ product: string; template: string }>();
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const [generationLocked, setGenerationLocked] = useState(true);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [selection, setSelection] = useState<{ name: string; assetKey: string; imageVersion: number; styleName: string; templateVersion: number; previewUri: string | null; poster?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [advanced, setAdvanced] = useState(false);
  const key = useRef("");
  const current = useRef<Draft>(EMPTY);
  const writes = useRef(Promise.resolve());
  useEffect(() => {
    let active = true;
    setBusy(true); setError(""); setSelection(null);
    void (async () => {
      try {
        const account = await req<{ email: string }>("/v1/account");
        const storageKey = `addy:campaign:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${product}:${template}`;
        const saved = await AsyncStorage.getItem(storageKey);
        const restored: Draft = saved ? JSON.parse(saved) : EMPTY;
        if (!restored.brief || Object.keys(EMPTY.brief).some(field => typeof restored.brief[field as keyof Brief] !== "string")) throw Error(tr("This campaign draft could not be read."));
        if (active) { key.current = storageKey; current.current = restored; setDraft(restored); }
        if (restored.campaignId) return;
        const [item, approved, catalogue] = await Promise.all([
          req<{ name: string }>(`/v1/products/${product}`),
          req<{ image: { version: number; assetKey: string } | null }>(`/v1/products/${product}/approved-image`),
          restored.command ? Promise.resolve({ items: [] }) : getCatalogue(),
        ]);
        const style = catalogue.items.find(value => value.id === template && value.outputKinds.includes("video"));
        const image = restored.command
          ? (await req<{ image: { version: number; assetKey: string } | null }>(`/v1/products/${product}/approved-image?version=${restored.command.body.imageVersion}`)).image
          : approved.image;
        if ((!style && !restored.command) || !image) throw Error(tr("Choose a valid style and approve your product photo in My Products first."));
        if (active) {
          key.current = storageKey; current.current = restored; setDraft(restored);
          setSelection({ poster: style?.poster ?? templatePreview(style, "photo") ?? undefined, name: item.name, assetKey: image.assetKey, imageVersion: image.version, styleName: style?.name ?? restored.command!.body.templateId, templateVersion: restored.command?.body.templateVersion ?? style!.version,
            previewUri: restored.command ? (typeof restored.command.previewUri === "string" ? restored.command.previewUri : null) : templatePreview(style, "video") });
        }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : tr("Could not load campaign.")); }
      finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, [product, template, reload]);

  async function persist(next: Draft) {
    current.current = next; setDraft(next);
    const storageKey = key.current, value = JSON.stringify(next);
    writes.current = writes.current.catch(() => {}).then(() => writeAccountDraft(storageKey, value));
    await writes.current;
  }
  async function save() {
    if (!selection || busy) return;
    setBusy(true); setError("");
    try {
      await writes.current;
      const command = current.current.command ?? { key: `campaign-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        previewUri: selection.previewUri,
        body: { ...current.current.brief, productId: product, imageVersion: selection.imageVersion, templateId: template, templateVersion: selection.templateVersion } };
      await persist({ ...current.current, command });
      const result = await req<{ id: string }>("/v1/campaigns", { method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body) });
      await persist({ ...current.current, campaignId: result.id });
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not save campaign. Retry the same action.")); }
    finally { setBusy(false); }
  }
  return <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1, backgroundColor: t.colors.bg }}>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 20, paddingTop: Math.max(insets.top, 18), paddingBottom: 24 }}>
    <TopBar title={tr("Customize campaign")} />
    {(!!selection || !!draft.campaignId) && <View style={{ gap: 12, marginTop: 16 }}>
      {!!selection && <Text>{selection.name} · {tr(selection.styleName)}</Text>}
      {draft.campaignId ? <>
        <CampaignDetails key={draft.campaignId} id={draft.campaignId} />
        <Button label={tr("Start another campaign")} disabled={busy} onPress={() => { setBusy(true); void persist(EMPTY).then(() => setReload(value => value + 1)).catch(e => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); }); }} />
      </> : selection && <>
        <Text>{tr("Style preview")}</Text>
        <StylePreview poster={selection.poster} uri={selection.previewUri} mode="video" controls compactControls />
        <Text>{tr("Results vary with your product. Review the generated campaign before using it.")}</Text>
        <Text>{tr("Your approved product image")}</Text>
        <ProductPreview assetKey={selection.assetKey} />
        <CampaignPlanner brief={draft.brief} assetKey={selection.assetKey} disabled={busy || !!draft.command || generationLocked}
          onChange={patch => { void persist({ ...current.current, brief: { ...current.current.brief, ...patch } }).catch(() => setError(tr("Could not save campaign planning."))); }} />
        <Button label={tr("More options")} variant="ghost" onPress={() => setAdvanced(!advanced)} />
        {advanced && <>
        <ApplyBrand disabled={busy || !!draft.command || generationLocked} onApply={({ color, font, contact, logoAssetKey }) => {
          void persist({ ...current.current, brief: { ...current.current.brief, color, font, contact, logoAssetKey } }).catch(() => setError(tr("Could not save brand settings.")));
        }} />
        <BrandFields value={draft.brief} disabled={busy || !!draft.command || generationLocked} onChange={patch => {
          void persist({ ...current.current, brief: { ...current.current.brief, ...patch } }).catch(() => setError(tr("Could not save brand settings.")));
        }} />
        </>}
        {([['offer', 'Offer', 300], ['instructions', 'Optional instructions', 500], ['caption', 'Caption', 2200], ['cta', 'Call to action', 100], ['color', 'Background color (#RRGGBB)', 7]] as const).filter(([field]) => advanced || field === 'offer' || field === 'cta' || (field === 'color' && !/^#[0-9a-f]{6}$/i.test(draft.brief.color))).map(([field, label, maxLength]) => field === "color" ? <ColorField key={field} label={tr(label)} value={draft.brief[field]} disabled={busy || !!draft.command || generationLocked} onChange={value => { void persist({ ...current.current, brief: { ...current.current.brief, color: value } }).catch(() => setError(tr("Could not save your draft."))); }} /> : <View key={field}>
          <Text>{tr(label)}</Text>
          <TextInput accessibilityLabel={tr(label)} value={draft.brief[field]} maxLength={maxLength} multiline editable={!busy && !draft.command && !generationLocked}
            autoCorrect autoCapitalize="sentences"
            onChangeText={value => { void persist({ ...current.current, brief: { ...current.current.brief, [field]: value } }).catch(() => setError(tr("Could not save your draft."))); }}
            style={{ color: t.colors.text, borderWidth: 1, borderColor: t.colors.borderStrong, padding: 12, minHeight: 44, borderRadius: 12 }} />
        </View>)}
        {!/^#[0-9a-fA-F]{6}$/.test(draft.brief.color) && <Text accessibilityRole="alert">{tr("Enter a background color as # followed by six hexadecimal characters, for example #12ABEF.")}</Text>}
        {advanced && <CampaignLogo assetKey={draft.brief.logoAssetKey} disabled={busy || !!draft.command || generationLocked} onBusyChange={setBusy}
          onChange={logoAssetKey => { void persist({ ...current.current, brief: { ...current.current.brief, logoAssetKey } }).catch(() => setError(tr("Could not save your logo selection."))); }} />}
        <Text variant="bodySm">{tr("Credits are reserved now; incomplete work may remain held for review. Spent on delivery or acceptance.")}</Text>
        <Text variant="bodySm">{tr("Save your campaign brief without spending credits. Review the pack price before generating.")}</Text>
        {!!draft.command && <Text>{tr("Submitted details are locked. Retry uses the same campaign request.")}</Text>}
        <Button label={draft.command ? tr("Retry same campaign") : tr("Save campaign brief")} variant="secondary" loading={busy} disabled={busy || generationLocked || !/^#[0-9a-fA-F]{6}$/.test(draft.brief.color)} onPress={() => void save()} />
      </>}
    </View>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {!selection && !draft.campaignId && <Button label={tr("Reload campaign draft")} disabled={busy} loading={busy} onPress={() => setReload(value => value + 1)} />}
    </ScrollView>
    {!draft.campaignId && <ScrollView keyboardShouldPersistTaps="handled" style={{ flexGrow: 0, maxHeight: "45%", borderTopWidth: 1, borderColor: t.colors.borderStrong }} contentContainerStyle={{ padding: 16, paddingBottom: Math.max(insets.bottom, 16) }}>
      <GenerateNewCampaign product={product} template={template} onLockedChange={setGenerationLocked} onStartNew={() => persist(EMPTY)}
        disabled={busy || !!draft.command || !/^#[0-9a-fA-F]{6}$/.test(draft.brief.color)}
        body={selection ? { ...draft.brief, productId: product, imageVersion: selection.imageVersion, templateId: template, templateVersion: selection.templateVersion } : null} />
    </ScrollView>}
  </KeyboardAvoidingView>;
}
