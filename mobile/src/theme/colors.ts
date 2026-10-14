/**
 * Color tokens extracted verbatim from the Claude Design handoff
 * (MobileAdMaker.dc.html). Dark-first; light is the L1/L2 variant.
 *
 * The teal accent and its on-accent ink (#04201c) are the brand constants —
 * identical in both schemes. Everything else flips.
 */

export const brand = {
  teal: "#00c2a8",
  tealBright: "#00d4c6",
  tealDeep: "#00a892",
  tealNeon: "#00e0cf",
  ink: "#04201c", // text/icons placed ON teal
} as const;

// Platform accent chips — the design used oklch(); converted to hex so they
// render on every RN version without a color-space polyfill.
export const platform = {
  tiktok: "#2ec5d4", // oklch(0.78 0.15 200) — cyan
  reels: "#e35d95", //  oklch(0.72 0.16 350) — pink
  feed: "#e6ac3d", //   oklch(0.80 0.15 85)  — amber (landscape frame)
  stories: "#b168d9", // oklch(0.72 0.16 300) — purple
} as const;

export const dark = {
  scheme: "dark" as const,
  bg: "#0e0e11",
  bgElevated: "#16161b", // bottom sheet
  surface: "rgba(255,255,255,0.03)",
  surfaceRaised: "rgba(255,255,255,0.05)",
  surfaceRaisedStrong: "rgba(255,255,255,0.06)",
  border: "rgba(255,255,255,0.08)",
  borderSubtle: "rgba(255,255,255,0.07)",
  borderStrong: "rgba(255,255,255,0.14)",

  text: "#f4f4f5",
  textSecondary: "rgba(255,255,255,0.55)",
  textMuted: "#a1a1aa",
  textFaint: "rgba(255,255,255,0.28)",

  accent: brand.teal,
  accentInk: brand.ink,
  accentTint: "rgba(0,194,168,0.13)",
  accentTintStrong: "rgba(0,194,168,0.16)",
  accentBorder: "rgba(0,194,168,0.28)",

  warning: "#e6ac3d",
  warningText: "#e9b45a",
  warningTint: "rgba(230,172,61,0.14)",
  danger: "#ff6b6b",

  tabBar: "rgba(14,14,17,0.96)",
  onMediaText: "#ffffff",
  onMediaScrim: "rgba(0,0,0,0.5)",
} as const;

export const light = {
  scheme: "light" as const,
  bg: "#f6f5f3",
  bgElevated: "#ffffff",
  surface: "#ffffff",
  surfaceRaised: "rgba(0,0,0,0.03)",
  surfaceRaisedStrong: "rgba(0,0,0,0.05)",
  border: "rgba(0,0,0,0.08)",
  borderSubtle: "rgba(0,0,0,0.07)",
  borderStrong: "rgba(0,0,0,0.14)",

  text: "#17171a",
  textSecondary: "rgba(0,0,0,0.5)",
  textMuted: "#66666d",
  textFaint: "rgba(0,0,0,0.3)",

  accent: brand.teal,
  accentInk: brand.ink,
  accentTint: "rgba(0,194,168,0.14)",
  accentTintStrong: "rgba(0,194,168,0.16)",
  accentBorder: "rgba(0,194,168,0.3)",

  warning: "#d98a2b",
  warningText: "#b06a15",
  warningTint: "rgba(230,172,61,0.16)",
  danger: "#e5484d",

  tabBar: "rgba(246,245,243,0.85)",
  onMediaText: "#ffffff",
  onMediaScrim: "rgba(0,0,0,0.5)",
} as const;

// Union so `isDark ? dark : light` type-checks; both share the same keys, so
// property access (t.colors.bg, …) is always safe.
export type Palette = typeof dark | typeof light;
