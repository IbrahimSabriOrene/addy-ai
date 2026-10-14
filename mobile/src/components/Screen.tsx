import React from "react";
import { View, ViewStyle, ScrollView, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

// On web there's no device status bar to offset content, so give a little top
// breathing room instead of letting the header hug the very top edge.
export const WEB_TOP_INSET = Platform.OS === "web" ? 18 : 0;
import { StatusBar } from "expo-status-bar";
import { useTheme } from "@/theme/ThemeProvider";

type Props = {
  children: React.ReactNode;
  /** Scrollable body (default) vs a fixed full-bleed layout. */
  scroll?: boolean;
  /** Skip the top safe-area inset (for full-bleed media screens). */
  edgeToEdge?: boolean;
  /** Background override (e.g. pure black for the video result screen). */
  background?: string;
  padded?: boolean;
  contentStyle?: ViewStyle;
  /** Extra bottom padding so content clears a floating tab bar / CTA. */
  bottomInset?: number;
  /** Full-bleed layer rendered behind all content (e.g. a <Glow />). */
  backgroundLayer?: React.ReactNode;
};

/**
 * Screen wrapper: applies the themed background, safe-area insets, and the
 * correct status-bar style. Replaces the design's hand-drawn phone chrome —
 * the notch, clock, and home indicator are the real OS here.
 */
export function Screen({
  children,
  scroll = true,
  edgeToEdge = false,
  background,
  padded = true,
  contentStyle,
  bottomInset = 0,
  backgroundLayer,
}: Props) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const bg = background ?? t.colors.bg;

  const inner: ViewStyle = {
    paddingTop: edgeToEdge ? 0 : Math.max(insets.top, WEB_TOP_INSET),
    paddingLeft: Math.max(padded ? t.space.screenX : 0, insets.left),
    paddingRight: Math.max(padded ? t.space.screenX : 0, insets.right),
    paddingBottom: (edgeToEdge ? 0 : insets.bottom) + bottomInset,
    flexGrow: 1,
  };

  return (
    <View style={{ flex: 1, backgroundColor: bg }}>
      <StatusBar style={t.isDark ? "light" : "dark"} />
      {backgroundLayer}
      {scroll ? (
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={[inner, contentStyle]}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          automaticallyAdjustKeyboardInsets
        >
          {children}
        </ScrollView>
      ) : (
        <View style={[inner, { flex: 1, minHeight: 0 }, contentStyle]}>{children}</View>
      )}
    </View>
  );
}
