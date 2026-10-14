import React from "react";
import { Pressable, View } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";

/** Pill switch matching the design (teal when on, knob slides). */
export function Toggle({
  value,
  onChange,
  size = "sm",
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  size?: "sm" | "md";
}) {
  const t = useTheme();
  const w = size === "sm" ? 38 : 44;
  const h = size === "sm" ? 22 : 26;
  const knob = h - 4;
  return (
    <Pressable
      onPress={() => onChange(!value)}
      accessibilityRole="switch"
      accessibilityState={{ checked: value }}
      style={{
        width: w,
        height: h,
        borderRadius: t.radius.pill,
        backgroundColor: value ? t.colors.accent : t.colors.surfaceRaisedStrong,
        justifyContent: "center",
      }}
    >
      <View
        style={{
          width: knob,
          height: knob,
          borderRadius: knob / 2,
          backgroundColor: "#fff",
          marginLeft: value ? w - knob - 2 : 2,
        }}
      />
    </Pressable>
  );
}
