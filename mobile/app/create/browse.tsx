import { useI18n, translate } from "@/i18n";
import { USE_MOCK } from "@/api/client";
import React, { useRef, useState } from "react";
import { FlatList, Pressable, ScrollView, View, type ViewToken } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/Button";
import { StylePreview } from "@/components/StylePreview";
import { getCatalogue, templatePreview, type Catalogue, type OutputKind } from "@/api/creation";
import { useTheme } from "@/theme/ThemeProvider";

export default function BrowseScreen() {
  useI18n();
  const router = useRouter();
  const { product, category: initialCategory } = useLocalSearchParams<{ product?: string; category?: string }>();
  const t = useTheme();
  const [mode, setMode] = useState<OutputKind>("video");
  const [category, setCategory] = useState(["food", "gifts", "jewelry", "beauty", "home", "fashion", "pets", "tech"].includes(initialCategory ?? "") ? initialCategory! : "");
  const categoryScroll = useRef<ScrollView>(null);
  const [look, setLook] = useState("");
  const [looksOpen, setLooksOpen] = useState(false);
  const [visibleId, setVisibleId] = useState<string | null>(null);
  const viewability = useRef({ itemVisiblePercentThreshold: 60 }).current;
  const onVisible = useRef(({ viewableItems }: { viewableItems: ViewToken[] }) => setVisibleId(viewableItems[0]?.item.id ?? null)).current;
  const catalogue = useQuery<Catalogue>({ queryKey: ["catalogue"], queryFn: getCatalogue, staleTime: 300000 });
  const data: Catalogue | undefined = catalogue.data;
  const categoryItems = data?.items.filter(item => item.outputKinds.includes(mode) && !!templatePreview(item, mode) && (!category || item.categories.includes(category))) ?? [];
  const looks = [...new Set(categoryItems.map(item => item.presentation).filter((value): value is string => !!value))];
  const items = categoryItems.filter(item => !look || item.presentation === look);
  return <Screen scroll={false} contentStyle={{ flex: 1 }}>
    <FlatList numColumns={2} columnWrapperStyle={{ gap: 12 }} showsVerticalScrollIndicator={false} data={items} keyExtractor={item => item.id} extraData={visibleId}
      viewabilityConfig={viewability} onViewableItemsChanged={onVisible} contentContainerStyle={{ paddingBottom: 24 }}
      ListHeaderComponent={<>
    <TopBar title={translate("Browse styles")} />
    <View style={{ flexDirection: "row", gap: 12, marginVertical: 16 }}>
      {(product ? ["video"] as const : ["video", "photo"] as const).map(kind => <Pressable key={kind} accessibilityRole="tab" accessibilityState={{ selected: mode === kind }}
        onPress={() => { setMode(kind); setLook(""); if (!data?.items.some(item => item.outputKinds.includes(kind) && item.categories.includes(category))) { setCategory(""); categoryScroll.current?.scrollTo({ x: 0, animated: false }); } }} style={{ flex: 1, minHeight: 48, justifyContent: "center", paddingVertical: 12, paddingHorizontal: 8, borderRadius: 12, backgroundColor: mode === kind ? t.colors.accent : t.colors.surface, borderWidth: 1, borderColor: mode === kind ? t.colors.accent : t.colors.border }}>
        <Text variant="bodySm" center color={mode === kind ? t.colors.accentInk : t.colors.text}>{kind === "video" ? translate("Video Ads") : translate("Product Photos")}</Text>
      </Pressable>)}
    </View>
    <ScrollView ref={categoryScroll} horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingBottom: 16 }}>
      {[{ id: "", name: "All" }, ...(catalogue.data?.categories.filter(value => data?.items.some(item => item.categories.includes(value.id) && item.outputKinds.includes(mode) && templatePreview(item, mode))) ?? [])].map(item => <Pressable key={item.id} accessibilityRole="button"
        accessibilityState={{ selected: category === item.id }} onPress={() => { setCategory(item.id); setLook(""); }} style={{ padding: 12, borderWidth: 1, borderRadius: 24, backgroundColor: category === item.id ? t.colors.accentTint : t.colors.surface, borderColor: category === item.id ? t.colors.accent : t.colors.borderStrong }}>
        <Text>{translate(item.name)}</Text>
      </Pressable>)}
    </ScrollView>
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
      <Text variant="caption" color={t.colors.textMuted}>{USE_MOCK ? translate("Concept previews") : translate("Styles")} · {items.length}</Text>
      {!!looks.length && <Pressable accessibilityRole="button" accessibilityLabel={translate("Filter presentation")} accessibilityState={{ expanded: looksOpen }} onPress={() => setLooksOpen(!looksOpen)} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 12, borderRadius: 12, backgroundColor: t.colors.surface }}>
        <Text variant="bodySm" color={look ? t.colors.accent : t.colors.text}>{translate(look || "All looks")} {looksOpen ? "−" : "+"}</Text>
      </Pressable>}
    </View>
    {looksOpen && <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, paddingTop: 8 }}>
      {["", ...looks].map(value => <Pressable key={value} accessibilityRole="button" accessibilityLabel={translate("Presentation: {name}", { name: translate(value || "All looks") })} accessibilityState={{ selected: look === value }} onPress={() => { setLook(value); setLooksOpen(false); }} style={{ minHeight: 44, paddingHorizontal: 12, justifyContent: "center", borderRadius: 22, borderWidth: 1, borderColor: look === value ? t.colors.accent : t.colors.borderStrong, backgroundColor: look === value ? t.colors.accentTint : t.colors.surface }}>
        <Text variant="bodySm">{translate(value || "All looks")}</Text>
      </Pressable>)}
    </View>}
    {catalogue.isPending && <Text>{translate("Loading styles…")}</Text>}
    {catalogue.isError && <><Text accessibilityRole="alert">{translate(catalogue.error.message)}</Text><Button label={translate("Reload styles")} onPress={() => void catalogue.refetch()} /></>}
    {!catalogue.isPending && !catalogue.isError && !items.length && <Text>{translate("No styles in this category yet.")}</Text>}
    </>}
    renderItem={({ item }) => <Pressable accessibilityRole="button" accessibilityLabel={translate("Customize {name}", { name: translate(item.name) })}
      onPress={() => router.push(product ? { pathname: "/create/campaign", params: { template: item.id, product } } : { pathname: "/create/customize", params: { template: item.id, mode } })}
      style={{ flex: 1, maxWidth: "50%", marginTop: 16, gap: 6 }}>
      <StylePreview poster={item.poster ?? templatePreview(item, "photo") ?? undefined} uri={templatePreview(item, mode)} mode={mode} aspectRatio={9 / 16} active={(items.some(value => value.id === visibleId) ? visibleId : items[0]?.id) === item.id} />
      <Text variant="subheading">{translate(item.name)}</Text>
      {!!item.presentation && <Text variant="caption" color={t.colors.textMuted}>{translate(item.presentation)}</Text>}

    </Pressable>} />
  </Screen>;
}
