/**
 * Theme context: resolves the active palette from the OS color scheme (the
 * design ships both dark and light variants), loads the Space Grotesk +
 * Manrope fonts, and exposes `useTheme()` to every component.
 */
import React, { createContext, useContext } from "react";
import { useColorScheme } from "react-native";
import { useFonts } from "expo-font";
import {
  SpaceGrotesk_500Medium,
  SpaceGrotesk_600SemiBold,
  SpaceGrotesk_700Bold,
} from "@expo-google-fonts/space-grotesk";
import {
  Manrope_400Regular,
  Manrope_500Medium,
  Manrope_600SemiBold,
  Manrope_700Bold,
} from "@expo-google-fonts/manrope";

import { dark, light, brand, platform, type Palette } from "./colors";
import { radius, space, type, fonts } from "./tokens";

export type Theme = {
  colors: Palette;
  brand: typeof brand;
  platform: typeof platform;
  radius: typeof radius;
  space: typeof space;
  type: typeof type;
  fonts: typeof fonts;
  isDark: boolean;
  fontsReady: boolean;
};

const ThemeContext = createContext<Theme | null>(null);

export function useTheme(): Theme {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>");
  return ctx;
}

const FORCE_DARK = true;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const isDark = FORCE_DARK ? true : scheme !== "light";
  const [loaded, error] = useFonts({
    SpaceGrotesk_500Medium,
    SpaceGrotesk_600SemiBold,
    SpaceGrotesk_700Bold,
    Manrope_400Regular,
    Manrope_500Medium,
    Manrope_600SemiBold,
    Manrope_700Bold,
  });
  // Treat a load error as "ready" so the app never hangs on the splash if a
  // font fails — it just falls back to system for that face.
  const fontsReady = loaded || !!error;

  const theme: Theme = {
    colors: isDark ? dark : light,
    brand,
    platform,
    radius,
    space,
    type,
    fonts,
    isDark,
    fontsReady,
  };

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}
