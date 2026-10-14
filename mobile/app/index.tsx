import React, { useEffect, useState } from "react";
import { View } from "react-native";
import { Redirect } from "expo-router";
import { useTheme } from "@/theme/ThemeProvider";
import { hasOnboarded } from "@/lib/onboarding";

/** Entry: route first-run users to onboarding, returning users straight in. */
export default function Index() {
  const t = useTheme();
  const [target, setTarget] = useState<"/onboarding" | "/home" | null>(null);

  useEffect(() => {
    hasOnboarded().then((seen) => setTarget(seen ? "/home" : "/onboarding"));
  }, []);

  if (!target) return <View style={{ flex: 1, backgroundColor: t.colors.bg }} />;
  return <Redirect href={target} />;
}
