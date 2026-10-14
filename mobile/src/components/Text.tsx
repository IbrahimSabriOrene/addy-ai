import React from "react";
import { Text as RNText, TextProps, TextStyle } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";
import type { TypeVariant } from "@/theme/tokens";

type Props = TextProps & {
  variant?: TypeVariant;
  color?: string;
  center?: boolean;
  /** Override the ramp's family (e.g. force a heavier weight). */
  family?: string;
};

/**
 * The single text primitive. `variant` selects a semantic ramp entry
 * (family + size + line-height + tracking); `color` defaults to primary text.
 */
export function Text({
  variant = "body",
  color,
  center,
  family,
  style,
  ...rest
}: Props) {
  const t = useTheme();
  const v = t.type[variant];
  const base: TextStyle = {
    fontFamily: family ?? v.family,
    fontSize: v.size,
    lineHeight: v.lineHeight,
    letterSpacing: "letterSpacing" in v ? (v as any).letterSpacing : 0,
    color: color ?? t.colors.text,
    textAlign: center ? "center" : undefined,
  };
  return <RNText {...rest} style={[base, style]} />;
}
