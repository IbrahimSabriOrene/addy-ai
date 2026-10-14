import "react-native-gesture-handler";
import React from "react";
import { I18nProvider } from "@/i18n";
import { View, Platform } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { ThemeProvider, useTheme } from "@/theme/ThemeProvider";
import { SessionBoundary } from "@/components/SessionBoundary";
import { EngagementBridge } from "@/components/EngagementBridge";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

function RootStack() {
  const t = useTheme();
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: t.colors.bg },
        animation: "slide_from_right",
      }}
    >
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="onboarding" options={{ animation: "fade" }} />
      <Stack.Screen name="sign-in" options={{ animation: "slide_from_right" }} />
      <Stack.Screen name="create" />
      <Stack.Screen name="paywall" options={{ presentation: "modal", animation: "slide_from_bottom" }} />
    </Stack>
  );
}

/**
 * Holds a dark splash until the Space Grotesk / Manrope fonts are in, so users
 * never see a flash of the fallback (system) font before they swap.
 */
function FontGate({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  if (!t.fontsReady) return <View style={{ flex: 1, backgroundColor: t.colors.bg }} />;
  return <>{children}</>;
}

/**
 * On native the app fills the device screen. On web (react-native-web fills
 * the whole browser window), we cap it to a phone-sized frame and center it,
 * so the mobile layout doesn't stretch on desktop. `position: relative`
 * keeps the absolutely-positioned tab bar / full-bleed screens anchored to
 * the frame, not the window.
 */
function AppFrame({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  if (Platform.OS !== "web") return <>{children}</>;
  return (
    <View style={{ flex: 1, backgroundColor: "#050506", alignItems: "center", justifyContent: "center" }}>
      <View
        style={{
          position: "relative",
          flex: 1,
          width: "100%",
          maxWidth: 430,
          maxHeight: 932,
          overflow: "hidden",
          backgroundColor: t.colors.bg,
          borderRadius: 24,
        }}
      >
        {children}
      </View>
    </View>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <I18nProvider><SessionBoundary>
          <ThemeProvider>
            <FontGate>
              <AppFrame>
                <RootStack />
                <EngagementBridge />
              </AppFrame>
            </FontGate>
          </ThemeProvider>
          </SessionBoundary></I18nProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
