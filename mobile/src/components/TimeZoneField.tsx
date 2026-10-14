import React, { useState } from "react";
import { View, TextInput } from "react-native";
import { useI18n } from "@/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { Button } from "./Button";
import { Text } from "./Text";

export function TimeZoneField({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (value: string) => void }) {
  const { tr } = useI18n(), t = useTheme();
  const [open, setOpen] = useState(false), [search, setSearch] = useState("");
  const device = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const available = (Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["UTC", "Europe/Istanbul", "Europe/London", "America/New_York", "America/Sao_Paulo", "Europe/Madrid"];
  let exact = "";
  try { if (search.trim()) exact = new Intl.DateTimeFormat("en", { timeZone: search.trim() }).resolvedOptions().timeZone; } catch { /* Search may be a partial city name. */ }
  const matches = [...new Set([value, device, exact, ...available].filter(Boolean))].filter(zone => zone.toLowerCase().replaceAll("_", " ").includes(search.toLowerCase().replaceAll("_", " ")) || zone === exact).slice(0, 8);
  return <View style={{ gap: 8 }}>
    <Button label={`${tr("Time zone")} · ${value.replaceAll("_", " ")}`} variant="secondary" disabled={disabled} onPress={() => setOpen(!open)} />
    {open && <>
      <TextInput accessibilityLabel={tr("Search time zones")} placeholder={tr("Search time zones")} placeholderTextColor={t.colors.textMuted} value={search} onChangeText={setSearch} editable={!disabled} autoCapitalize="none" autoCorrect={false}
        style={{ minHeight: 44, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: t.colors.borderStrong, color: t.colors.text }} />
      {matches.map(zone => <Button key={zone} label={zone.replaceAll("_", " ")} variant={zone === value ? "selected" : "secondary"} disabled={disabled} onPress={() => { onChange(zone); setOpen(false); }} />)}
      {!matches.length && <Text>{tr("No matching time zone")}</Text>}
    </>}
    <Button label={tr("Use this device's time zone")} variant="ghost" disabled={disabled} onPress={() => onChange(device)} />
  </View>;
}
