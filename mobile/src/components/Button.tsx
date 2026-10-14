import React from "react";
import { Pressable, View, ViewStyle, ActivityIndicator } from "react-native";
import * as Haptics from "expo-haptics";
import { useTheme } from "@/theme/ThemeProvider";
import { Text } from "./Text";

type Variant = "primary" | "secondary" | "ghost" | "selected" | "danger";

type Props = {
  label: string;
  onPress?: () => void;
  variant?: Variant;
  icon?: React.ReactNode; // leading icon
  trailing?: React.ReactNode; // trailing element (e.g. a −1 credit pill)
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  haptic?: boolean;
};

/**
 * The design's three button treatments:
 *  - primary   → solid teal, dark ink, teal glow shadow (the main CTA)
 *  - secondary → hairline outline, primary text
 *  - ghost     → text-only row (e.g. "Try a different direction")
 */
export function Button({
  label,
  onPress,
  variant = "primary",
  icon,
  trailing,
  loading,
  disabled,
  style,
  haptic = true,
}: Props) {
  const t = useTheme();
  const isSelected = variant === "selected";
  const isPrimary = variant === "primary";
  const isSecondary = variant === "secondary";

  const height = isPrimary ? 56 : 52;
  const container: ViewStyle = {
    minHeight: height,
    paddingVertical: 12,
    borderRadius: isPrimary ? t.radius.lg + 1 : t.radius.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: trailing ? "space-between" : "center",
    gap: 9,
    paddingHorizontal: trailing ? t.space.xl : 16,
    opacity: disabled ? 0.5 : 1,
    ...(isPrimary && {
      backgroundColor: t.colors.accent,
      shadowColor: t.colors.accent,
      shadowOpacity: 0.14,
      shadowRadius: 12,
      shadowOffset: { width: 0, height: 10 },
      elevation: 8,
    }),
    ...(isSelected && { backgroundColor: t.colors.accentTint, borderWidth: 1.5, borderColor: t.colors.accent }),
    ...(variant === "danger" && { borderWidth: 1.5, borderColor: t.colors.danger }),
    ...(isSecondary && {
      borderWidth: 1,
      borderColor: t.colors.borderStrong,
    }),
  };

  const inkColor = variant === "danger" ? t.colors.danger : isSelected ? t.colors.accent : isPrimary ? t.colors.accentInk : t.colors.text;

  const onPressWrapped = () => {
    if (disabled || loading) return;
    if (haptic) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    onPress?.();
  };

  return (
    <Pressable
      onPress={onPressWrapped}
      disabled={disabled || loading}
      style={({ pressed }) => [container, { opacity: pressed ? 0.9 : container.opacity }, style]}
      accessibilityRole="button"
      aria-pressed={isSelected ? true : undefined}
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled || loading), busy: Boolean(loading), selected: isSelected }}
    >
      {variant === "ghost" ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 1 }}>
          {loading ? <ActivityIndicator color={t.colors.textSecondary} /> : icon}
          <Text variant="buttonSm" color={t.colors.textSecondary} style={{ flexShrink: 1, textAlign: "center" }}>
            {label}
          </Text>
        </View>
      ) : (
        <>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 9, flexShrink: 1 }}>
            {loading ? <ActivityIndicator color={inkColor} /> : isSelected ? <Text color={inkColor}>✓</Text> : icon}
            <Text variant={isPrimary ? "button" : "buttonSm"} color={inkColor} style={{ flexShrink: 1, textAlign: "center" }}>
              {label}
            </Text>
          </View>
          {trailing}
        </>
      )}
    </Pressable>
  );
}
