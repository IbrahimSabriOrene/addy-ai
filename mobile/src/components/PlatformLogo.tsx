import React from "react";
import Svg, { Path, Rect, Circle } from "react-native-svg";
import type { PlatformKey } from "@/api/types";

export function PlatformLogo({ platform, size = 18, color = "#fff" }: { platform: PlatformKey; size?: number; color?: string }) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden={true}>
    {platform === "tiktok" ? <Path fill={color} d="M16.7 1h-3.6v14.8a3.2 3.2 0 1 1-2.8-3.2V9a6.8 6.8 0 1 0 6.4 6.8V8.3a9 9 0 0 0 5.3 1.7V6.4A5.4 5.4 0 0 1 16.7 1Z" />
      : platform === "reels" ? <>
        <Rect x="3" y="3" width="18" height="18" rx="5" stroke={color} strokeWidth="1.8" />
        <Path d="M3 9h18M8 3l4 6m3-6 4 6" stroke={color} strokeWidth="1.8" />
        <Path d="m10 12 6 3.5-6 3.5Z" fill={color} />
      </> : <>
        <Rect x="3" y="3" width="18" height="18" rx="5" stroke={color} strokeWidth="1.8" />
        <Circle cx="12" cy="12" r="4" stroke={color} strokeWidth="1.8" />
        <Circle cx="17.5" cy="6.5" r="1" fill={color} />
      </>}
  </Svg>;
}
