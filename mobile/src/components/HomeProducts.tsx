import { translate as tr, useI18n } from "@/i18n";
import React, { useCallback } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { req, USE_MOCK } from "@/api/client";
import { demoProducts } from "./DemoControls";
import { Text } from "./Text";
import { Button } from "./Button";
import { useTheme } from "@/theme/ThemeProvider";

export function HomeProducts() {
  useI18n();
  const router = useRouter();
  const t = useTheme();
  const products = useQuery({ queryKey: ["home-products"], queryFn: async () => USE_MOCK
    ? { items: [...demoProducts] }
    : req<{ items: { id: string; name: string }[] }>("/v1/products?limit=6") });
  useFocusEffect(useCallback(() => { void products.refetch(); }, [products.refetch]));
  return <View style={{ marginTop: 20, gap: 8 }}>
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
      <Text variant="subheading">{tr("My Products")}</Text>
      <Button label={tr("View all products")} variant="ghost" onPress={() => router.push("/products")} />
    </View>
    {products.isPending && <Text>{tr("Loading products…")}</Text>}
    {products.isError && <Button label={tr("Retry products")} variant="ghost" onPress={() => void products.refetch()} />}
    {products.data?.items.length === 0 && <Button label={tr("Save your first product")} variant="secondary" onPress={() => router.push("/products")} />}
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
      {products.data?.items.slice(0, 6).map(product => <Pressable key={product.id} accessibilityRole="button"
        accessibilityLabel={tr("View {v0} creations", { v0: product.name })} onPress={() => router.push({ pathname: "/product", params: { id: product.id } })}
        style={{ padding: 16, minHeight: 64, maxWidth: 200, borderRadius: 16, backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.border }}>
        <Text variant="cardTitle" numberOfLines={2}>{product.name}</Text>
        <Text variant="caption" color={t.colors.textMuted}>{tr("View creations →")}</Text>
      </Pressable>)}
    </ScrollView>
  </View>;
}
