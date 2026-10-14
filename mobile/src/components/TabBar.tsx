import { useI18n, translate } from "@/i18n";
import React from "react";
import { View, Pressable } from "react-native";
import { BlurView } from "expo-blur";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import type { BottomTabBarProps } from "expo-router/js-tabs";
import { useTheme } from "@/theme/ThemeProvider";
import { Text } from "./Text";
import { Home, Plus, Grid, User } from "./Icons";

const ICONS: Record<string, (c: string) => React.ReactNode> = {
  home: (c) => <Home color={c} />,
  library: (c) => <Grid color={c} />,
  account: (c) => <User color={c} />,
};
const LABELS: Record<string, string> = { home: "Home", library: "Library", account: "Account" };

/**
 * Frosted bottom tab bar matching the handoff: blurred translucent surface,
 * teal active tint, 10px labels. "Create" isn't a route — it's injected here
 * (after Home) and launches the create flow, so it never collides with the
 * /create/* stack.
 */
export function TabBar({ state, navigation }: BottomTabBarProps) {
  useI18n();
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const item = (routeName: string, key: string) => {
    const routeIndex = state.routes.findIndex((r) => r.name === routeName);
    const focused = state.index === routeIndex;
    const color = focused ? t.colors.accent : t.colors.textMuted;
    return (
      <Pressable
        key={key}
        onPress={() => {
          const route = state.routes[routeIndex];
          const event = navigation.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
          if (!focused && !event.defaultPrevented) navigation.navigate(route.name);
        }}
        style={{ flex: 1, minHeight: 44, justifyContent: "center", alignItems: "center", gap: 5 }}
        accessibilityRole="button"
        accessibilityLabel={translate(LABELS[routeName])}
        accessibilityState={{ selected: focused }}
      >
        {ICONS[routeName]?.(color)}
        <Text variant="tab" family={focused ? t.fonts.bodySemi : t.fonts.body} color={color}>
          {translate(LABELS[routeName])}
        </Text>
      </Pressable>
    );
  };

  return (
    <BlurView
      intensity={30}
      tint={t.isDark ? "dark" : "light"}
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        paddingTop: 13,
        paddingBottom: Math.max(insets.bottom, 10),
        paddingLeft: Math.max(16, insets.left),
        paddingRight: Math.max(16, insets.right),
        flexDirection: "row",
        backgroundColor: t.colors.tabBar,
        borderTopWidth: 1,
        borderTopColor: t.colors.borderSubtle,
      }}
    >
      {item("home", "home")}
      {/* Create — injected button, not a route */}
      <Pressable
        onPress={() => router.push("/create/browse")}
        style={{ flex: 1, minHeight: 44, justifyContent: "center", alignItems: "center", gap: 5 }}
        accessibilityRole="button"
        accessibilityLabel={translate("Create")}
      >
        <Plus color={t.colors.textMuted} />
        <Text variant="tab" family={t.fonts.body} color={t.colors.textMuted}>
          {translate("Create")}</Text>
      </Pressable>
      {item("library", "library")}
      {item("account", "account")}
    </BlurView>
  );
}

/** Height reserved for the tab bar so scroll content clears it. */
export const TAB_BAR_HEIGHT = 90;
