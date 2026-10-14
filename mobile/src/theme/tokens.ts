/** Spacing, radius, and typography scales derived from the handoff. */

export const radius = {
  sm: 9,
  md: 12,
  lg: 16,
  xl: 18,
  xxl: 20,
  card: 22,
  hero: 24,
  sheet: 30,
  pill: 999,
} as const;

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 26,
  screenX: 24, // default horizontal screen padding (handoff used 24–26)
} as const;

// Font families — loaded in ThemeProvider via @expo-google-fonts.
export const fonts = {
  display: "SpaceGrotesk_700Bold",
  displayMed: "SpaceGrotesk_600SemiBold",
  displayReg: "SpaceGrotesk_500Medium",
  body: "Manrope_500Medium",
  bodyReg: "Manrope_400Regular",
  bodySemi: "Manrope_600SemiBold",
  bodyBold: "Manrope_700Bold",
  mono: "ui-monospace",
} as const;

/**
 * Semantic type ramp. `family` picks Space Grotesk for structural/heading text
 * and Manrope for prose — matching the design exactly.
 */
export const type = {
  displayLg: { family: fonts.display, size: 29, lineHeight: 33, letterSpacing: -0.6 },
  display: { family: fonts.display, size: 24, lineHeight: 29, letterSpacing: -0.4 },
  title: { family: fonts.display, size: 22, lineHeight: 26, letterSpacing: -0.4 },
  heading: { family: fonts.display, size: 19, lineHeight: 24, letterSpacing: -0.2 },
  subheading: { family: fonts.display, size: 16, lineHeight: 21 },
  cardTitle: { family: fonts.display, size: 15, lineHeight: 20 },
  button: { family: fonts.display, size: 16.5, lineHeight: 20 },
  buttonSm: { family: fonts.display, size: 15, lineHeight: 19 },
  body: { family: fonts.bodyReg, size: 14, lineHeight: 21 },
  bodyStrong: { family: fonts.bodySemi, size: 14, lineHeight: 21 },
  bodySm: { family: fonts.bodyReg, size: 13, lineHeight: 19 },
  caption: { family: fonts.bodyReg, size: 12, lineHeight: 17 },
  label: { family: fonts.bodySemi, size: 11, lineHeight: 15 },
  tab: { family: fonts.body, size: 11, lineHeight: 15 },
  eyebrow: { family: fonts.displayMed, size: 13, lineHeight: 16, letterSpacing: 1.4 },
} as const;

export type TypeVariant = keyof typeof type;
