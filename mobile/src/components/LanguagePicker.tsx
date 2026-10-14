import React, { useState } from "react";
import { View, Pressable } from "react-native";
import { useI18n, LOCALES, LANGUAGE_NAMES } from "@/i18n";
import { Text } from "./Text";
import { useTheme } from "@/theme/ThemeProvider";
import { req, USE_MOCK } from "@/api/client";
import { getToken } from "@/lib/auth";

export function LanguagePicker() {
  const { locale, setLocale, tr } = useI18n();
  const t = useTheme();
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [syncError, setSyncError] = useState(false);
  return <View style={{ gap: 12 }}>
    {LOCALES.map(value => <Pressable key={value} accessibilityRole="radio" aria-checked={locale === value} accessibilityState={{ checked: locale === value, disabled: busy }} disabled={busy}
      onPress={() => {
        setBusy(true); setError(false); setSyncError(false);
        void (async () => {
          try { await setLocale(value); } catch { setError(true); return; }
          try { if (!USE_MOCK && await getToken()) await req("/v1/account/language", { method: "PUT", body: JSON.stringify({ locale: value }) }); }
          catch { setSyncError(true); }
        })().finally(() => setBusy(false));
      }}
      style={{ minHeight: 48, padding: 14, borderRadius: 12, borderWidth: 1, borderColor: locale === value ? t.colors.accent : t.colors.border }}>
      <Text>{LANGUAGE_NAMES[value]}{locale === value ? " ✓" : ""}</Text>
    </Pressable>)}
    {error && <Text accessibilityRole="alert">{tr("Could not save your language. Please try again.")}</Text>}
    {syncError && <Text accessibilityRole="alert">{tr("App language saved on this device. Notification language could not be updated. Select the language again to retry.")}</Text>}
  </View>;
}
