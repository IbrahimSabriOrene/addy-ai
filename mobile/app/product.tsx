import { translate as tr, useI18n } from "@/i18n";
import React from "react";
import { View, Image, Pressable } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { req, USE_MOCK } from "@/api/client";
import { MOCK_CREATION_MEDIA } from "@/api/mock";
import { demoProducts } from "@/components/DemoControls";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { useTheme } from "@/theme/ThemeProvider";
import { Play } from "@/components/Icons";
import { ProductCampaigns } from "@/components/ProductCampaigns";

export default function ProductScreen() {
  useI18n();
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const t = useTheme();
  const product = useQuery({ queryKey: ["product", id], queryFn: async () => {
    if (!USE_MOCK) return req<{ id: string; name: string }>(`/v1/products/${encodeURIComponent(id)}`);
    const item = demoProducts.find(item => item.id === id);
    if (!item) throw new Error(tr("Product not found."));
    return item;
  }, enabled: !!id });
  return <Screen bottomInset={24}>
    <TopBar title={product.data?.name ?? tr("Product")} fallbackHref="/products" right={<Pressable accessibilityRole="button" accessibilityLabel={tr("Manage products")} onPress={() => router.push("/products")} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 8 }}><Text variant="bodySm" color={t.colors.textMuted}>{tr("Manage")}</Text></Pressable>} />
    {product.isPending && <Text>{tr("Loading product…")}</Text>}
    {product.isError && <><Text accessibilityRole="alert">{tr(product.error.message)}</Text><Button label={tr("Try again")} onPress={() => void product.refetch()} /></>}
    {product.data && <View style={{ gap: 16, marginTop: 20 }}>
      <Button label={tr("Create new ad")} onPress={() => router.push(USE_MOCK ? "/create/browse" : { pathname: "/create/browse", params: { product: id } })} />
      <Text variant="subheading">{tr("Creations")}</Text>
      {USE_MOCK ? id === "demo-mug" ? <>
        <Pressable accessibilityRole="button" accessibilityLabel={tr("Open ceramic mug video")} onPress={() => router.push("/create/result?id=job_1")}
          style={{ flexDirection: "row", alignItems: "center", gap: 14, padding: 12, borderRadius: 18, backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.border }}>
          <Image source={MOCK_CREATION_MEDIA.job_1.photo} accessibilityLabel={tr("Ceramic mug ad")} resizeMode="cover" style={{ width: 88, height: 112, borderRadius: 10 }} />
          <View style={{ flex: 1, gap: 6 }}>
            <Text variant="cardTitle">{tr("Pedestal spin")}</Text>
            <Text variant="caption" color={t.colors.textMuted}>{tr("Video · 6 sec")}</Text>
            <Text variant="caption" color={t.colors.textMuted}>{tr("Demo sample")}</Text>
          </View>
          <View style={{ width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: t.colors.surfaceRaised }}>
            <Play size={16} color={t.colors.accent} />
          </View>
        </Pressable>
      </> : <Text>{tr("No creations yet. Create your first ad for this product.")}</Text>
        : <ProductCampaigns productId={id} />}
    </View>}
  </Screen>;
}
