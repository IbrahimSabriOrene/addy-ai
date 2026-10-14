import React from "react";
import { Stack } from "expo-router";
import { useTheme } from "@/theme/ThemeProvider";

export default function CreateLayout() {
  const t = useTheme();
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: t.colors.bg },
      }}
    >
      <Stack.Screen name="upload" />
      <Stack.Screen name="style" />
      <Stack.Screen name="generating" options={{ gestureEnabled: false }} />
      <Stack.Screen name="result" options={{ animation: "fade" }} />
      <Stack.Screen name="reshoot" options={{ animation: "fade" }} />
      <Stack.Screen name="decision" options={{ presentation: "transparentModal", animation: "fade" }} />
    </Stack>
  );
}
