import { useI18n, translate } from "@/i18n";
import React from "react";
import { Image } from "react-native";
import { usePrivateMedia } from "@/lib/usePrivateMedia";
import { Text } from "./Text";

export function ProductPreview({ assetKey }: { assetKey: string }) {
  useI18n();
  const api = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/v1\/?$/, "");
  const { source, error } = usePrivateMedia(`${api}/v1/assets/${encodeURIComponent(assetKey)}`);
  if (error) return <Text accessibilityRole="alert">{translate(error)}</Text>;
  return source ? <Image accessibilityLabel={translate("Selected product photo")} source={source} resizeMode="contain" style={{ width: "100%", height: 180 }} /> : <Text>{translate("Loading product photo…")}</Text>;
}
