import React, { useEffect } from "react";
import { View } from "react-native";
import Svg, { Circle } from "react-native-svg";
import Animated, { useSharedValue, useAnimatedStyle, withRepeat, withTiming, Easing } from "react-native-reanimated";
import { useTheme } from "@/theme/ThemeProvider";
import { Text } from "./Text";

/**
 * The Generating-screen gauge: a slowly-rotating dashed outer ring (design
 * decoration) around a teal progress arc, with the percentage + ETA centered.
 */
export function ProgressRing({
  progress, // 0..100
  eta,
  size = 200,
}: {
  progress: number;
  eta?: string;
  size?: number;
}) {
  const t = useTheme();

  // Gauge sits inset from the edge so the dashed ring has a visible gap.
  const stroke = 28;
  const r = size / 2 - stroke; // outer edge ≈ 0.86·size
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, progress));
  const dash = (pct / 100) * c;

  // Outer dashed ring, rotating.
  const dashR = size / 2 - 1;
  const rot = useSharedValue(0);
  useEffect(() => {
    rot.value = withRepeat(withTiming(360, { duration: 14000, easing: Easing.linear }), -1);
  }, []);
  const spin = useAnimatedStyle(() => ({ transform: [{ rotate: `${rot.value}deg` }] }));

  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      {/* rotating dashed decoration */}
      <Animated.View style={[{ position: "absolute", width: size, height: size }, spin]}>
        <Svg width={size} height={size}>
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={dashR}
            stroke={"rgba(0,194,168,0.3)"}
            strokeWidth={2}
            strokeDasharray={"3 9"}
            fill="none"
          />
        </Svg>
      </Animated.View>

      {/* progress gauge */}
      <Svg width={size} height={size} style={{ transform: [{ rotate: "-90deg" }] }}>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={t.colors.border} strokeWidth={stroke} fill="none" />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={t.colors.accent}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c - dash}`}
          fill="none"
        />
      </Svg>

      <View style={{ position: "absolute", alignItems: "center" }}>
        <Text family={t.fonts.display} color={t.colors.text} style={{ fontSize: 44, lineHeight: 46 }}>
          {Math.round(pct)}
          <Text family={t.fonts.display} color={t.colors.textSecondary} style={{ fontSize: 20 }}>
            %
          </Text>
        </Text>
        {eta ? (
          <Text variant="caption" color={t.colors.textSecondary} style={{ marginTop: 2 }}>
            {eta}
          </Text>
        ) : null}
      </View>
    </View>
  );
}
