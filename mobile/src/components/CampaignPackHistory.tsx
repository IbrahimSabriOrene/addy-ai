import { translate as tr, useI18n } from "@/i18n";
import React, { useEffect, useState } from "react";
import { View } from "react-native";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { EarlierCampaignRequests } from "./EarlierCampaignRequests";
import { CampaignResults } from "./CampaignResults";

type Page = { items: { version: number; createdAt: string; jobState: string }[]; nextBeforeVersion: number | null };

export function CampaignPackHistory({ campaignId, currentVersion }: { campaignId: string; currentVersion: number }) {
  useI18n();
  const [items, setItems] = useState<Page["items"]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  async function load(before?: number) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const page = await req<Page>(`/v1/campaigns/${campaignId}/generations${before ? `?beforeVersion=${before}` : ""}`);
      setItems(old => before ? [...old, ...page.items.filter(item => !old.some(existing => existing.version === item.version))] : page.items);
      setCursor(page.nextBeforeVersion); setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load pack history.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [campaignId, currentVersion]);
  return <View style={{ gap: 12 }}>
    <EarlierCampaignRequests campaignId={campaignId} currentVersion={currentVersion} />
    <Text>{tr("Generated campaign packs")}</Text>
    <Text>{tr("Saved text is version {v0}. Earlier packs keep their original offer and media.", { v0: currentVersion })}</Text>
    {loaded && !items.length && <Text>{tr("No campaign packs generated yet.")}</Text>}
    {items.map(item => <Button key={item.version} label={tr("{v0} pack version {v1}", { v0: selected === item.version ? tr("Close") : tr("View"), v1: item.version })} variant="secondary"
      onPress={() => setSelected(selected === item.version ? null : item.version)} />)}
    {selected !== null && <CampaignResults key={`${campaignId}-${selected}`} campaignId={campaignId} version={selected} />}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    <Button label={tr("Refresh pack history")} variant="ghost" loading={busy} disabled={busy} onPress={() => void load()} />
    {cursor !== null && <Button label={tr("Load older packs")} disabled={busy} onPress={() => void load(cursor)} />}
  </View>;
}
