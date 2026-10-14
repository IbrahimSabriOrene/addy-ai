import React from "react";
import { Image, ImageSourcePropType, View, ViewStyle, StyleSheet } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";
import { Text } from "./Text";

/** Media frame. Missing media is an explicit unavailable state, never a fake image. */
export function MediaPlaceholder({ label, style, children, source }: {
  label?: string;
  tone?: "neutral" | "teal" | "warn" | "video";
  style?: ViewStyle;
  children?: React.ReactNode;
  source?: ImageSourcePropType;
}) {
  const t = useTheme();
  return <View style={[{ backgroundColor: t.colors.surface, overflow: "hidden", alignItems: "center", justifyContent: "center" }, style]}>
    {source ? <Image source={source} accessibilityLabel={label ?? "Product preview"} resizeMode="cover" style={[StyleSheet.absoluteFill, { width: "100%", height: "100%" }]} />
      : <Text variant="label" color={t.colors.textMuted}>{label ?? "Preview unavailable"}</Text>}
    {children}
  </View>;
}
