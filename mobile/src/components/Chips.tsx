import { useI18n, translate } from "@/i18n";
import { PlatformLogo } from "./PlatformLogo";
import React from "react";
import { View, ViewStyle } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";
import { Text } from "./Text";
import type { PlatformKey } from "@/api/types";

/** Small teal "N credits" pill used in the top bar and paywall header. */
export function CreditChip({ credits, solid = false }: { credits: number; solid?: boolean }) {
  const t = useTheme();
  useI18n();
  const wrap: ViewStyle = {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    paddingHorizontal: 13,
    paddingVertical: 8,
    borderRadius: t.radius.pill,
    backgroundColor: solid ? t.colors.accent : t.colors.accentTint,
    borderWidth: solid ? 0 : 1,
    borderColor: t.colors.accentBorder,
  };
  return (
    <View style={wrap}>
      <View
        style={{
          width: 8,
          height: 8,
          borderRadius: 4,
          backgroundColor: solid ? t.colors.accentInk : t.colors.accent,
        }}
      />
      <Text variant="label" family={t.fonts.display} color={solid ? t.colors.accentInk : t.colors.accent} style={{ fontSize: 13 }}>
        {credits} {translate(credits === 1 ? "credit" : "credits")}
      </Text>
    </View>
  );
}

type Status = "delivered" | "in_progress" | "needs_reshoot";

/** Job-status pill (Library rows, Home cards). */
export function StatusPill({ status, progress }: { status: Status; progress?: number }) {
  const t = useTheme();
  useI18n();
  const map = {
    delivered: { label: "Delivered", color: t.colors.accent, tint: t.colors.accentTint, dot: true },
    in_progress: {
      label: "In progress",
      color: t.colors.warningText,
      tint: t.colors.warningTint,
      dot: true,
    },
    needs_reshoot: { label: "Needs reshoot", color: t.colors.warningText, tint: t.colors.warningTint, dot: false },
  }[status];

  return (
    <View
      style={{
        alignSelf: "flex-start",
        flexDirection: "row",
        alignItems: "center",
        gap: 5,
        paddingHorizontal: 9,
        paddingVertical: 3,
        borderRadius: t.radius.pill,
        backgroundColor: map.tint,
      }}
    >
      {map.dot && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: map.color }} />}
      <Text variant="label" family={t.fonts.display} color={map.color}>
        {translate(map.label)}
      </Text>
    </View>
  );
}

const PLATFORM_META: Record<PlatformKey, { label: string; landscape?: boolean }> = {
  tiktok: { label: "TikTok" },
  reels: { label: "Reels" },
  feed: { label: "Feed", landscape: true },
  stories: { label: "Stories" },
};

/** Platform logo and label, with a selected state. */
export function PlatformChip({
  platform: key,
  active = false,
  onMedia = false,
  onPress,
}: {
  platform: PlatformKey;
  active?: boolean;
  onMedia?: boolean;
  onPress?: () => void;
}) {
  const t = useTheme();
  useI18n();
  const meta = PLATFORM_META[key];

  // On a video (onMedia): active = white pill w/ dark text; inactive = frosted.
  const bg = onMedia
    ? active
      ? "#fff"
      : "rgba(255,255,255,0.12)"
    : active
      ? t.colors.accent
      : t.colors.surfaceRaised;
  const textColor = onMedia ? (active ? "#111" : "#fff") : active ? t.colors.accentInk : t.colors.textSecondary;

  const Wrapper: any = onPress ? require("react-native").Pressable : View;
  return (
    <Wrapper
      onPress={onPress}
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={translate(meta.label)}
      aria-pressed={onPress ? active : undefined}
      accessibilityState={onPress ? { selected: active } : undefined}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
        paddingHorizontal: 13,
        paddingVertical: 8,
        minHeight: onPress ? 44 : undefined,
        borderRadius: t.radius.pill,
        backgroundColor: bg,
      }}
    >
      <PlatformLogo platform={key} color={textColor} />
      <Text variant="label" family={active ? t.fonts.bodyBold : t.fonts.bodySemi} color={textColor} style={{ fontSize: 12 }}>
        {translate(meta.label)}
      </Text>
    </Wrapper>
  );
}

/** Compact platform logo badge for thumbnails. */
export function PlatformDot({ platform: key }: { platform: PlatformKey }) {
  const t = useTheme();
  return <View style={{ padding: 3, borderRadius: 5, backgroundColor: t.colors.surfaceRaised }}>
    <PlatformLogo platform={key} size={14} color={t.colors.text} />
  </View>;
}
