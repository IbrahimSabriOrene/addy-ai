import React, { useId, useState } from "react";
import { View, StyleSheet, LayoutChangeEvent } from "react-native";
import Svg, { Defs, RadialGradient, Stop, Rect } from "react-native-svg";

/**
 * The teal radial wash the design places behind the onboarding hero (top) and
 * the generating gauge (upper-center). Reproduces the design's CSS
 * `radial-gradient(RX RY at CX CY, color 0%, bg FADE%)`. Sits as an absolute
 * background layer; pointer-events off so it never blocks touches.
 *
 * Sizing: the container is measured via onLayout and the SVG is drawn at
 * concrete pixel dimensions — percentage-sized SVGs render unreliably on
 * react-native-web when the parent is absolutely stretched (same fix as
 * MediaPlaceholder).
 */
export function Glow({
  color = "#12332f",
  cx = "50%",
  cy = "0%",
  rx = "120%",
  ry = "90%",
  fadeEnd = 0.46,
}: {
  color?: string;
  /** Ellipse center, % of width. */
  cx?: string;
  /** Ellipse center, % of height. */
  cy?: string;
  /** Horizontal radius, % of width. */
  rx?: string;
  /** Vertical radius, % of height. */
  ry?: string;
  /** Gradient stop (0–1) where the wash fully fades out. */
  fadeEnd?: number;
}) {
  // Unique gradient id per instance — DOM ids are global on web.
  const id = "glow-" + useId().replace(/[:]/g, "");
  const [size, setSize] = useState({ w: 0, h: 0 });
  const onLayout = (e: LayoutChangeEvent) =>
    setSize({ w: Math.ceil(e.nativeEvent.layout.width), h: Math.ceil(e.nativeEvent.layout.height) });
  const pct = (v: string, base: number) => (parseFloat(v) / 100) * base;

  const cxPx = pct(cx, size.w);
  const cyPx = pct(cy, size.h);
  const rxPx = pct(rx, size.w);
  const ryPx = pct(ry, size.h);

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none" onLayout={onLayout}>
      {size.w > 0 && (
        <Svg width={size.w} height={size.h}>
          <Defs>
            {/* A circular objectBoundingBox gradient on a 2rx × 2ry rect
                stretches into the design's ellipse — the RadialGradient rx/ry
                props are ignored by browsers on the web renderer. */}
            <RadialGradient id={id} cx="50%" cy="50%" r="50%">
              <Stop offset="0" stopColor={color} stopOpacity={1} />
              <Stop offset={String(fadeEnd)} stopColor={color} stopOpacity={0} />
            </RadialGradient>
          </Defs>
          <Rect x={cxPx - rxPx} y={cyPx - ryPx} width={rxPx * 2} height={ryPx * 2} fill={`url(#${id})`} />
        </Svg>
      )}
    </View>
  );
}
