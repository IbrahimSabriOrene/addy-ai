import React from "react";
import { View, ViewStyle, Pressable } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";

type Props = {
  children: React.ReactNode;
  style?: ViewStyle;
  /** Lavender-tinted selected state (e.g. the chosen style candidate). */
  selected?: boolean;
  padded?: boolean;
  onPress?: () => void;
  radius?: number;
};

/** Neutral surface card — the repeated container across list/detail screens. */
export function Card({ children, style, selected, padded = true, onPress, radius }: Props) {
  const t = useTheme();
  const base: ViewStyle = {
    borderRadius: radius ?? t.radius.xl,
    padding: padded ? t.space.lg : 0,
    backgroundColor: selected ? "#302844" : t.colors.surface,
    borderWidth: selected ? 1.5 : 1,
    borderColor: selected ? "#BCA3F5" : t.colors.borderSubtle,
  };
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [base, pressed && { opacity: 0.85 }, style]}>
        {children}
      </Pressable>
    );
  }
  return <View style={[base, style]}>{children}</View>;
}
