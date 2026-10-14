import React, { useEffect } from "react";
import { View } from "react-native";
import Animated, { useSharedValue, useAnimatedStyle, withRepeat, withTiming, Easing } from "react-native-reanimated";
import { useTheme } from "@/theme/ThemeProvider";

/** Teal ring spinner (the "in progress" indicator), Reanimated-driven. */
export function Spinner({ size = 18, color }: { size?: number; color?: string }) {
  const t = useTheme();
  const rot = useSharedValue(0);
  useEffect(() => {
    rot.value = withRepeat(withTiming(360, { duration: 900, easing: Easing.linear }), -1);
  }, []);
  const style = useAnimatedStyle(() => ({ transform: [{ rotate: `${rot.value}deg` }] }));
  return (
    <Animated.View
      style={[
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          borderWidth: 2,
          borderColor: color ?? t.colors.accent,
          borderTopColor: "transparent",
        },
        style,
      ]}
    >
      <View />
    </Animated.View>
  );
}
