import { useI18n, translate } from "@/i18n";
import React from "react";
import { View, Pressable } from "react-native";
import { type Href, useRouter } from "expo-router";
import { useTheme } from "@/theme/ThemeProvider";
import { Text } from "./Text";
import { ChevronBack } from "./Icons";

/** Back chevron in a rounded square + optional title — the create-flow header. */
export function TopBar({
  title,
  right,
  onBack,
  fallbackHref = "/home",
  onMedia = false,
}: {
  title?: string;
  right?: React.ReactNode;
  onBack?: () => void;
  fallbackHref?: Href;
  onMedia?: boolean;
}) {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const iconColor = onMedia ? "#fff" : t.colors.text;
  const back = onBack ?? (() => (router.canGoBack() ? router.back() : router.replace(fallbackHref)));
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 12, minHeight: 44 }}>
      <Pressable
        onPress={back}
        hitSlop={10}
        style={{
          width: 44,
          height: 44,
          flexShrink: 0,
          borderRadius: t.radius.md,
          backgroundColor: onMedia ? "rgba(0,0,0,0.4)" : t.colors.surfaceRaisedStrong,
          alignItems: "center",
          justifyContent: "center",
        }}
        accessibilityRole="button"
        accessibilityLabel={translate("Back")}
      >
        <ChevronBack color={iconColor} />
      </Pressable>
      {title ? (
        <Text variant="heading" color={iconColor} style={{ flex: 1 }}>
          {title}
        </Text>
      ) : (
        <View style={{ flex: 1 }} />
      )}
      {right}
    </View>
  );
}
