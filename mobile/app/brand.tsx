import { ColorField } from "@/components/ColorField";
import { translate as tr, useI18n } from "@/i18n";
import React, { useEffect, useState } from "react";
import { View, TextInput } from "react-native";
import { req } from "@/api/client";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { CampaignLogo } from "@/components/CampaignLogo";
import { BrandFields, BrandProfile } from "@/components/BrandFields";
import { useTheme } from "@/theme/ThemeProvider";

export default function BrandScreen() {
  useI18n();
  const t = useTheme();
  const [record, setRecord] = useState<{ version: number; profile: BrandProfile } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  async function load() {
    setBusy(true); setError(""); setNotice("");
    try { setRecord(await req("/v1/account/brand")); }
    catch (e) { setError(e instanceof Error ? e.message : tr("Could not load brand.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  async function save() {
    if (!record || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      setRecord(await req("/v1/account/brand", { method: "PUT", body: JSON.stringify({ ...record.profile, expectedVersion: record.version }) }));
      setNotice(tr("Brand saved. Apply it when customizing a campaign; existing campaigns stay unchanged."));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not save brand.")); }
    finally { setBusy(false); }
  }
  return <Screen bottomInset={24}><TopBar title={tr("Brand profile")} />
    {record && <View style={{ gap: 12, marginTop: 16 }}>
      {([['name', 'Brand name', 100], ['color', 'Brand color (#RRGGBB)', 7]] as const).map(([field, label, maxLength]) => field === "color" ? <ColorField key={field} label={tr(label)} value={record.profile[field]} disabled={busy} onChange={value => setRecord({ ...record, profile: { ...record.profile, color: value } })} /> : <View key={field}>
        <Text>{tr(label)}</Text><TextInput accessibilityLabel={tr(label)} value={record.profile[field]} maxLength={maxLength} editable={!busy}
          autoCapitalize="words" autoCorrect={false}
          onChangeText={value => setRecord({ ...record, profile: { ...record.profile, [field]: value } })}
          style={{ color: t.colors.text, borderWidth: 1, borderColor: t.colors.borderStrong, padding: 12, minHeight: 44 }} />
      </View>)}
      <BrandFields expanded value={record.profile} disabled={busy} onChange={patch => setRecord({ ...record, profile: { ...record.profile, ...patch } })} />
      <CampaignLogo context="brand" assetKey={record.profile.logoAssetKey} disabled={busy} onBusyChange={setBusy}
        onChange={logoAssetKey => setRecord(current => current ? { ...current, profile: { ...current.profile, logoAssetKey } } : current)} />
      {!/^#[0-9a-fA-F]{6}$/.test(record.profile.color) && <Text accessibilityRole="alert">{tr("Enter a color such as #12ABEF.")}</Text>}
      <Button label={tr("Save brand profile")} loading={busy} disabled={busy || !/^#[0-9a-fA-F]{6}$/.test(record.profile.color)} onPress={() => void save()} />
    </View>}
    {!!notice && <Text accessibilityLiveRegion="polite">{tr(notice)}</Text>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {(!record || !!error) && <Button label={tr("Reload brand and discard local edits")} variant="secondary" disabled={busy} onPress={() => void load()} />}
  </Screen>;
}
