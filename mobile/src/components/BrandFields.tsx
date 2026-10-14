import { translate as tr, useI18n } from "@/i18n";
import React, { useState } from "react";
import { View, TextInput } from "react-native";
import { req } from "@/api/client";
import { useTheme } from "@/theme/ThemeProvider";
import { Button } from "./Button";
import { Text } from "./Text";

export type BrandStyle = { font?: "sans" | "serif"; contact?: string };
export type BrandProfile = BrandStyle & { name: string; color: string; logoAssetKey?: string | null };

export function BrandFields({ value, disabled, onChange, expanded = false }: {
  value: BrandStyle; disabled: boolean; onChange: (patch: BrandStyle) => void; expanded?: boolean;
}) {
  useI18n();
  const t = useTheme();
  const [open, setOpen] = useState(expanded);
  return <View style={{ gap: 10 }}>
    {!expanded && <Button label={open ? tr("Close brand options") : tr("Brand options")} variant="ghost" onPress={() => setOpen(!open)} />}
    {open && <>
    <Text>{tr("Layout font")}</Text>
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {(["sans", "serif"] as const).map(font => <Button key={font} label={font === "sans" ? tr("Sans serif") : tr("Serif")}
        variant={(value.font ?? "sans") === font ? "selected" : "secondary"} disabled={disabled} onPress={() => onChange({ font })} />)}
    </View>
    <Text>{tr("Contact shown on layouts")}</Text>
    <TextInput accessibilityLabel={tr("Contact shown on layouts")} value={value.contact ?? ""} maxLength={100} editable={!disabled}
      autoCapitalize="none" autoCorrect={false} onChangeText={contact => onChange({ contact })}
      style={{ color: t.colors.text, borderWidth: 1, borderColor: t.colors.borderStrong, padding: 12, minHeight: 44 }} />
    </>}
  </View>;
}

export function ApplyBrand({ disabled, onApply }: { disabled: boolean; onApply: (profile: BrandProfile) => void }) {
  useI18n();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function apply() {
    setBusy(true); setError("");
    try {
      const result = await req<{ version: number; profile: BrandProfile }>("/v1/account/brand");
      if (!result.version) throw Error(tr("Save your brand profile in Account first."));
      onApply(result.profile);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load brand profile.")); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 8 }}>
    <Button label={tr("Apply saved brand")} variant="secondary" disabled={disabled || busy} loading={busy} onPress={() => void apply()} />
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View>;
}
