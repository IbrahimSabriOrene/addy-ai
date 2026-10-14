import { useI18n, translate as tr } from "@/i18n";
import React from "react";
import { View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { StylePreview } from "@/components/StylePreview";
import { Asset } from "expo-asset";

const segments = {
  bakery: { title: "A campaign for your next bake", category: "food", caption: "Bring your own product photo and exact offer. Prepare a weekend launch, then reuse your approved image next time.", image: require("../public/previews/bakery_morning.photo.jpg") },
  handmade: { title: "Show the detail in what you make", category: "gifts", caption: "Start with your own product and brand. Create coordinated campaign assets and review the result before sharing.", image: require("../public/previews/gift_unwrap.photo.jpg") },
};
export default function BusinessLandingScreen() {
  const { locale } = useI18n();
  const { segment } = useLocalSearchParams<{ segment?: string }>();
  const selected = segments[segment === "bakery" ? "bakery" : "handmade"];
  return <Screen bottomInset={24}><TopBar title={tr("Addy AI for your business")} /><View style={{ gap: 16, marginTop: 20 }}>
    <Text variant="display">{tr(selected.title)}</Text>
    <StylePreview uri={Asset.fromModule(selected.image).uri} mode="photo" />
    <Text>{tr("Concept example, not a validated output for your product.")}</Text>
    <Text>{tr(selected.caption)}</Text>
    <Text>{tr("Review the full generation price before spending credits. Updating on-screen offers uses eligible delivered video without another paid video call.")}</Text>
    <Button label={tr("Explore examples for my business")} onPress={() => router.push({ pathname: "/create/browse", params: { category: selected.category } })} />
    <Button label={tr("Browse every category")} variant="secondary" onPress={() => router.push("/create/browse")} />
  </View></Screen>;
}
