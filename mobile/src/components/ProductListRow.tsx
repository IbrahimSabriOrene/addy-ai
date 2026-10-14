import { translate as tr, useI18n } from "@/i18n";
import React from "react";
import { Image, Pressable, View, type ImageSourcePropType } from "react-native";
import { Text } from "./Text";
import { useTheme } from "@/theme/ThemeProvider";

export function ProductListRow({ name, photo, onOpen, onOptions, expanded }: { name: string; photo?: ImageSourcePropType; onOpen: () => void; onOptions: () => void; expanded: boolean }) {
  useI18n();
  const t = useTheme();
  return <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
    <Pressable accessibilityRole="button" accessibilityLabel={tr("View {v0}", { v0: name })} onPress={onOpen} style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: 14, minHeight: 80 }}>
      {photo ? <Image source={photo} resizeMode="cover" style={{ width: 56, height: 64, borderRadius: 12 }} />
        : <View style={{ width: 56, height: 64, borderRadius: 12, backgroundColor: t.colors.accentTint, alignItems: "center", justifyContent: "center" }}><Text variant="title" color={t.colors.accent}>{name.charAt(0).toUpperCase()}</Text></View>}
      <View style={{ flex: 1, gap: 4 }}><Text variant="cardTitle" numberOfLines={2}>{name}</Text><Text variant="caption" color={t.colors.textMuted}>{tr("View creations ›")}</Text></View>
    </Pressable>
    <Pressable accessibilityRole="button" accessibilityLabel={tr("Options for {v0}", { v0: name })} accessibilityState={{ expanded }} onPress={onOptions} style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}><Text style={{ fontSize: 24 }} color={t.colors.textMuted}>⋯</Text></Pressable>
  </View>;
}
