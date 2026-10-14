import { useI18n, translate } from "@/i18n";
import { createDemoJob } from "@/api/demoJobs";
import { demoProducts } from "@/components/DemoControls";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import { Image, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, TextInput, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as ImagePicker from "expo-image-picker";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Button } from "@/components/Button";
import { Text } from "@/components/Text";
import { TopBar } from "@/components/TopBar";
import { StylePreview } from "@/components/StylePreview";
import { ProductPreview } from "@/components/ProductPreview";
import { ResumeSignIn } from "@/components/ResumeSignIn";
import { req, uploadImage, USE_MOCK } from "@/api/client";
import { createFromDraft, getCatalogue, templatePreview, type Catalogue, type CreationDraft, type Product } from "@/api/creation";
import { useTheme } from "@/theme/ThemeProvider";

const CREATIVE_TOOLS = {
  Background: ["Warm stone pedestal", "Clean studio backdrop", "Natural interior"],
  Lighting: ["Soft daylight", "Warm golden light", "Dramatic side lighting"],
  Motion: ["Slow camera orbit", "Gentle push in", "Static camera"],
};
const EMPTY: CreationDraft = { assetKey: "", productName: "", direction: "" };
type Consent = { granted: boolean; disclosureVersion: string; disclosure: string };

export default function CustomizeScreen() {
  useI18n();
  const { template, mode } = useLocalSearchParams<{ template: string; mode: string }>();
  const router = useRouter();
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const qc = useQueryClient();
  const catalogue = useQuery<Catalogue>({ queryKey: ["catalogue"], queryFn: getCatalogue });
  const modeSettings = mode === "photo" || mode === "video" ? catalogue.data?.modes?.[mode] : undefined;
  const data: Catalogue | undefined = catalogue.data ? { ...catalogue.data, ...modeSettings } : undefined;
  const selected = data?.items.find(item => item.id === template && item.outputKinds.some(kind => kind === mode));
  const [draft, setDraft] = useState<CreationDraft>(EMPTY);
  const current = useRef<CreationDraft>(EMPTY);
  const storageKey = useRef("");
  const writes = useRef(Promise.resolve());
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uri, setUri] = useState("");
  const [saveName, setSaveName] = useState("");
  const [saved, setSaved] = useState(false);
  const [productsOpen, setProductsOpen] = useState(false);
  const [tool, setTool] = useState<keyof typeof CREATIVE_TOOLS | null>(null);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [consentOpen, setConsentOpen] = useState(false);
  const products = useInfiniteQuery({ queryKey: ["creation-products", storageKey.current], enabled: !USE_MOCK && ready,
    initialPageParam: "", queryFn: ({ pageParam }) => req<{ items: Product[]; nextCursor: string | null }>(`/v1/products${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`),
    getNextPageParam: page => page.nextCursor ?? undefined });

  useEffect(() => {
    let active = true;
    setReady(false);
    void (async () => {
      try {
        const account = USE_MOCK ? { email: "demo" } : await req<{ email: string }>("/v1/account");
        const key = `addy:create:${process.env.EXPO_PUBLIC_API_URL ?? "demo"}:${account.email}:${template}:${mode}`;
        const value = await AsyncStorage.getItem(key);
        const stored = value ? JSON.parse(value) : EMPTY;
        if (!stored || typeof stored.assetKey !== "string" || typeof stored.direction !== "string" || typeof stored.productName !== "string") throw Error("This draft could not be read.");
        if (active) { storageKey.current = key; current.current = stored; setDraft(stored); setReady(true); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Could not load your draft."); }
    })();
    return () => { active = false; };
  }, [template, mode]);

  async function persist(next: CreationDraft) {
    current.current = next;
    setDraft(next);
    const key = storageKey.current;
    const value = JSON.stringify(next);
    writes.current = writes.current.catch(() => {}).then(() => writeAccountDraft(key, value));
    await writes.current;
  }

  async function action(work: () => Promise<void>) {
    setBusy(true); setError("");
    try { await work(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not complete this action. Your draft is retained."); }
    finally { setBusy(false); }
  }

  async function pick() {
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
    if (result.canceled) return;
    const image = result.assets[0];
    const assetKey = USE_MOCK ? "demo-local-preview" : await uploadImage(image.uri);
    await persist({ ...current.current, assetKey, productName: "Uploaded product" });
    setUri(image.uri); setSaved(false);
  }

  async function selectProduct(product: Product) {
    const approved = await req<{ image: { assetKey: string } | null }>(`/v1/products/${product.id}/approved-image`);
    await persist({ ...current.current, assetKey: approved.image?.assetKey ?? product.assetKey, productName: product.name });
    setUri(""); setSaved(true);
  }

  async function saveProduct() {
    await req("/v1/products", { method: "POST", headers: { "Idempotency-Key": `product-${draft.assetKey}` },
      body: JSON.stringify({ name: saveName.trim(), assetKey: draft.assetKey }) });
    await persist({ ...current.current, productName: saveName.trim() });
    setSaved(true);
    await products.refetch();
  }

  async function generate() {
    if (USE_MOCK) {
      if (!selected || (mode !== "photo" && mode !== "video")) return;
      const sample = templatePreview(selected, mode);
      if (!sample) return;
      const job = await createDemoJob({ title: `${selected.name} · Demo`, outputKind: mode,
        sourceImage: selected.poster ?? templatePreview(selected, "photo") ?? undefined,
        platforms: mode === "photo" ? ["feed"] : ["reels"],
        exports: [{ platform: mode === "photo" ? "feed" : "reels", url: Platform.OS === "web" ? sample.replace(/\.preview\.mp4$/, ".mp4").replace(/\.photo\.jpg$/, ".png") : sample,
          caption: `Discover a new look with ${selected.name}. #smallbusiness` }] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      router.push(`/create/generating?id=${job.id}`);
      return;
    }
    if (current.current.jobId) { router.push(`/create/generating?id=${current.current.jobId}`); return; }
    if (mode !== "photo" && mode !== "video") return;
    if (!current.current.command && (!selected || !data?.generationEnabled || !current.current.assetKey)) return;
    await writes.current;
    // A fixture never transfers media. An AI catalogue must explicitly disclose consent.
    if (!current.current.command && (data?.requiresAiConsent || data?.executionMode !== "fixture")) {
      const permission = await req<Consent>("/v1/account/ai-consent");
      if (!permission.granted) { setConsent(permission); setConsentOpen(true); return; }
    }
    setConsentOpen(false);
    const command = current.current.command ?? {
      key: `create-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      body: { assetKey: current.current.assetKey, platforms: mode === "photo" ? ["feed"] : ["reels"],
        fastMode: true, quality: "fast" as const, templateId: selected!.id, templateVersion: selected!.version,
        outputKind: mode, direction: current.current.direction },
    };
    // Persist the exact action before POST. An ambiguous response must reuse it.
    await persist({ ...current.current, command });
    const job = await createFromDraft(command);
    await persist({ ...current.current, jobId: job.id });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
    void qc.invalidateQueries({ queryKey: ["wallet"] });
    router.push(`/create/generating?id=${job.id}`);
  }

  async function allowSharing() {
    if (!consent) return;
    await req("/v1/account/ai-consent", { method: "PUT",
      body: JSON.stringify({ granted: true, disclosureVersion: consent.disclosureVersion }) });
    // Recheck server permission, including disclosure version, before creating the job.
    await generate();
  }

  async function refreshDisclosure() {
    setConsent(await req<Consent>("/v1/account/ai-consent"));
  }

  const locked = busy || !ready || !!draft.command;
  const price = mode === "photo" || mode === "video" ? catalogue.data?.prices[mode] : undefined;
  return <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1, backgroundColor: t.colors.bg }}>
    <ScrollView showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 20, paddingTop: Math.max(insets.top, 18), gap: 16 }}>
      <TopBar title={translate("Customize")} />
      <View style={{ padding: 14, gap: 12, borderRadius: 20, backgroundColor: t.colors.surface }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text variant="subheading">{translate(selected?.name ?? "Choose a style")}</Text>
          <Text variant="caption" color={t.colors.textMuted}>{translate("Style preview")}</Text>
        </View>
        <View style={{ width: "100%", maxWidth: 240, alignSelf: "center" }}>
          <StylePreview poster={selected?.poster ?? templatePreview(selected, "photo") ?? undefined} uri={mode === "photo" || mode === "video" ? templatePreview(selected, mode) : null} mode={mode === "photo" ? "photo" : "video"} controls compactControls aspectRatio={9 / 16} />
        </View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }} accessibilityLabel={translate("Style choices")}>
        {data?.items.filter(item => item.outputKinds.some(kind => kind === mode)).map(item =>
          <Pressable key={item.id} accessibilityRole="button" accessibilityLabel={translate("Choose {name}", { name: translate(item.name) })} accessibilityState={{ selected: item.id === template, disabled: locked }}
            disabled={locked} onPress={() => router.replace({ pathname: "/create/customize", params: { template: item.id, mode } })}
            style={{ width: 76, gap: 6 }}>
            <Image source={{ uri: item.poster ?? templatePreview(item, "photo") ?? undefined }}
              style={{ width: 76, height: 92, borderRadius: 12, borderWidth: 2, borderColor: item.id === template ? t.colors.accent : "transparent" }} />
            <Text variant="caption" center color={item.id === template ? t.colors.accent : t.colors.textSecondary}>{translate(item.name)}</Text>
          </Pressable>)}
      </ScrollView>
      <View style={{ flexDirection: "row", gap: 8 }}>
        {(Object.keys(CREATIVE_TOOLS) as (keyof typeof CREATIVE_TOOLS)[]).filter(name => mode === "video" || name !== "Motion").map(name =>
          <Pressable key={name} accessibilityRole="button" aria-pressed={tool === name} accessibilityState={{ selected: tool === name, disabled: locked }}
            disabled={locked} onPress={() => setTool(tool === name ? null : name)}
            style={{ flex: 1, minHeight: 56, justifyContent: "center", borderRadius: 14, backgroundColor: tool === name ? t.colors.accentTint : t.colors.surfaceRaised, borderWidth: 1, borderColor: tool === name ? t.colors.accent : t.colors.border }}>
            <Text center variant="bodySm" color={tool === name ? t.colors.accent : t.colors.text}>{translate(name)}</Text>
          </Pressable>)}
      </View>
      {tool && <View style={{ gap: 8, padding: 12, borderRadius: 16, backgroundColor: t.colors.surface }}>
        <Text variant="caption" color={t.colors.textSecondary}>{translate("Choose a direction for your next generation")}</Text>
        {CREATIVE_TOOLS[tool].map(option => {
          const instruction = `${tool}: ${option}.`;
          const active = draft.direction.split("\n").includes(instruction);
          return <Pressable key={option} accessibilityRole="button" accessibilityLabel={translate(option)} aria-pressed={active} accessibilityState={{ selected: active, disabled: locked }}
            disabled={locked} onPress={() => {
              const lines = current.current.direction.split("\n").filter(line => !CREATIVE_TOOLS[tool].some(value => line === `${tool}: ${value}.`));
              const direction = [...lines.filter(Boolean), ...(active ? [] : [instruction])].join("\n");
              if (direction.length > 500) { setError("Shorten your creative direction before adding another choice."); return; }
              void persist({ ...current.current, direction }).catch(() => setError("Could not save your draft."));
            }}
            style={{ minHeight: 44, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: active ? t.colors.accent : t.colors.border, backgroundColor: active ? t.colors.accentTint : "transparent" }}>
            <Text variant="bodySm" color={active ? t.colors.accent : t.colors.text}>{translate(option)}{active ? translate(" · Selected") : ""}</Text>
          </Pressable>;
        })}
      </View>}
      <Text variant="caption" color={t.colors.textMuted}>{USE_MOCK ? translate("Demo · Sample preview. Your edits are saved; they won’t change this sample.") : data?.executionMode === "fixture" ? translate("Local test · No AI styling; video audio is silent.") : translate("AI may change product details. Review before posting.")}</Text>
      {catalogue.isError && <Text accessibilityRole="alert">{translate(catalogue.error.message)}</Text>}
      {!selected && !catalogue.isPending && <Button label={translate("Browse styles")} onPress={() => router.replace("/create/browse")} />}
      {!ready && !error && <Text>{translate("Loading your saved draft…")}</Text>}
      <View style={{ padding: 16, gap: 12, borderRadius: 18, backgroundColor: t.colors.surface }}>
      <Text variant="subheading">{translate("Your product")}</Text>
      {!!uri && <Image source={{ uri }} accessibilityLabel={translate("Your uploaded product")} style={{ width: "100%", height: 100, resizeMode: "contain" }} />}
      {!USE_MOCK && !uri && !!draft.assetKey && <ProductPreview assetKey={draft.assetKey} />}
      {!!draft.assetKey && <Text accessibilityLiveRegion="polite" variant="bodySm">{draft.productName}</Text>}
      <Button label={draft.assetKey ? translate("Upload a different product") : translate("Upload product photo")} variant="secondary" disabled={locked} onPress={() => void action(pick)} />
      <Button label={productsOpen ? translate("Close saved products") : translate("Choose saved product")} variant="ghost" disabled={locked} onPress={() => setProductsOpen(!productsOpen)} />
      {productsOpen && <View style={{ gap: 8 }}>
      {USE_MOCK && demoProducts.map(product => <Button key={product.id} label={translate("Use {name}", { name: product.name })} variant="secondary" disabled={locked} onPress={() => void action(async () => { await persist({ ...current.current, assetKey: "demo-local-preview", productName: product.name }); setSaved(true); })} />)}
      {products.data?.pages.flatMap(page => page.items).map(product => <Button key={product.id} label={translate("Use {name}", { name: product.name })} variant="secondary" disabled={locked} onPress={() => void action(() => selectProduct(product))} />)}
      {products.isError && <><Text accessibilityRole="alert">{translate(products.error.message)}</Text><Button label={translate("Reload products")} onPress={() => void products.refetch()} /></>}
      {products.hasNextPage && <Button label={translate("More products")} loading={products.isFetchingNextPage} onPress={() => void products.fetchNextPage()} />}
      </View>}
      <Text variant="caption" color={t.colors.textMuted}>{translate("Use photos you own or have permission to use.")}</Text>
      {!USE_MOCK && !!draft.assetKey && !saved && !draft.command && <>
        <TextInput accessibilityLabel={translate("Product name")} placeholder={translate("Name this product")} value={saveName} onChangeText={setSaveName} maxLength={100} editable={!locked}
          placeholderTextColor={t.colors.textSecondary} style={{ color: t.colors.text, padding: 14, borderWidth: 1, borderColor: t.colors.borderStrong }} />
        <Button label={translate("Save this product")} variant="secondary" disabled={locked || !saveName.trim()} onPress={() => void action(saveProduct)} />
      </>}
      </View>
      <Text variant="subheading">{translate("Creative direction")}<Text variant="caption" color={t.colors.textMuted}>{translate("· Optional")}</Text></Text>
      <TextInput accessibilityLabel={translate("Anything you'd like to change?")} multiline maxLength={500} value={draft.direction} editable={!locked}
        placeholder={mode === "photo" ? translate("Use a pink background and soft lighting.") : translate("Use a pink background and a slow camera movement.")} placeholderTextColor={t.colors.textSecondary}
        onChangeText={direction => { void persist({ ...current.current, direction }).catch(() => setError("Could not save your draft. Check available storage.")); }}
        style={{ color: t.colors.text, minHeight: 80, borderRadius: 14, backgroundColor: t.colors.surface, textAlignVertical: "top", padding: 14, borderWidth: 1, borderColor: t.colors.borderStrong }} />

      {!!draft.command && !draft.jobId && <Text>{translate("The submitted details are locked. Retry checks the same action so it cannot create a second job.")}</Text>}
      {!!draft.command && !draft.jobId && (mode === "photo" || mode === "video") && <Button label={translate("Check balance and get credits")} variant="secondary" disabled={busy}
        onPress={() => router.push({ pathname: "/paywall", params: { returnTo: `/create/customize?${new URLSearchParams({ template, mode })}` } })} />}
      {!!draft.jobId && <Button label={translate("Start another draft")} variant="secondary" disabled={busy} onPress={() => void action(async () => { await persist(EMPTY); setUri(""); setSaved(false); })} />}
      {!!error && <Text accessibilityRole="alert">{translate(error)}</Text>}
      <ResumeSignIn error={error} returnTo={`/create/customize?${new URLSearchParams({ template, mode })}`} />
      {!USE_MOCK && data && !data.generationEnabled && !draft.jobId && <Text>{translate("Generation is currently unavailable for this mode. Your draft is saved.")}</Text>}
    </ScrollView>
    <View style={{ padding: 16, paddingBottom: Math.max(insets.bottom, 16), gap: 8, borderTopWidth: 1, borderColor: t.colors.borderStrong }}>
      {consentOpen && consent && <Modal visible animationType="slide" transparent onRequestClose={() => setConsentOpen(false)}>
        <View accessibilityViewIsModal style={{ flex: 1, justifyContent: "center", padding: 20, backgroundColor: "rgba(0,0,0,0.75)" }}>
        <ScrollView style={{ maxHeight: "90%", backgroundColor: t.colors.bg, borderRadius: 16 }} contentContainerStyle={{ padding: 20, gap: 14 }}>
        <Text variant="heading">{translate("Create with Addy AI")}</Text>
        <Text>{translate(consent.disclosure)}</Text>
        <Text>{translate("Photo-library access is separate. Declining keeps your draft and does not start generation.")}</Text>
        {!!error && <Text accessibilityRole="alert">{translate(error)}</Text>}
        <Button label={translate("Allow AI processing")} disabled={busy} onPress={() => void action(allowSharing)} />
        <Button label={translate("Do not allow")} variant="secondary" disabled={busy} onPress={() => { setConsentOpen(false); setError("AI sharing was not allowed. Your draft is saved."); }} />
        <Button label={translate("Refresh disclosure")} variant="ghost" disabled={busy} onPress={() => void action(refreshDisclosure)} />
        </ScrollView>
        </View>
      </Modal>}
      {!USE_MOCK && <Text center>{mode === "photo" ? translate("One product photo") : translate("One video")}{data?.executionMode === "fixture" ? translate(" · local test credits") : ""}</Text>}
      <Button label={USE_MOCK ? translate("Preview demo · Free") : draft.jobId ? translate("Open generation") : draft.command ? translate("Retry same generation") : translate("Generate · {count} credits", { count: price ?? "—" })}
        loading={busy} disabled={consentOpen || !ready || (!USE_MOCK && !draft.jobId && !draft.command && (!selected || !draft.assetKey || !data?.generationEnabled))} onPress={() => void action(generate)} />
    </View>
  </KeyboardAvoidingView>;
}
