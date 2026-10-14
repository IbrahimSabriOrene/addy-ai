import { useI18n, translate } from "@/i18n";
import React from "react";
import { Image } from "react-native";
import { usePrivateMedia } from "@/lib/usePrivateMedia";
import { Text } from "./Text";

export function ResultPhoto({ url }: { url: string }) {
  useI18n();
  const { source, error } = usePrivateMedia(url);
  if (error) return <Text accessibilityRole="alert">{translate(error)}</Text>;
  return source ? <Image accessibilityLabel={translate("Your generated product photo")} source={source} resizeMode="contain"
    style={{ position: "absolute", width: "100%", height: "100%" }} /> : null;
}
