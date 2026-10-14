import { translate as tr, useI18n } from "@/i18n";
import React, { useEffect, useState } from "react";
import { Image, View } from "react-native";
import { req } from "@/api/client";
import { usePrivateMedia } from "@/lib/usePrivateMedia";
import { Button } from "./Button";
import { Text } from "./Text";
import { ExportMedia } from "./ExportMedia";
import { CampaignVideoEdit } from "./CampaignVideoEdit";

type Output = { url: string; width: number; height: number; offer: string; cta: string };
type Layouts = { version: number; state: "ready" | "not_generated"; outputs: Partial<Record<"story" | "feed", Output>> & { video?: Output & { sourceVersion: number } } };

function LayoutPreview({ kind, output }: { kind: string; output: Output }) {
  useI18n();
  const api = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/v1\/?$/, "");
  const { source, error } = usePrivateMedia(`${api}${output.url}`);
  return <View style={{ gap: 8 }}>
    <Text>{kind === "story" ? tr("Story") : tr("Feed image")}</Text>
    {error ? <Text accessibilityRole="alert">{tr(error)}</Text> : source ?
      <Image source={source} accessibilityLabel={tr("{v0}: {v1}. {v2}", { v0: kind === "story" ? tr("Story") : tr("Feed image"), v1: output.offer, v2: output.cta })} resizeMode="contain"
        style={{ width: "100%", aspectRatio: output.width / output.height }} /> : <Text>{tr("Loading image…")}</Text>}
    <ExportMedia url={`${api}${output.url}`} filename={`addy-${kind}.png`} mimeType="image/png" />
  </View>;
}

export function CampaignLayouts({ campaignId, version, disabled }: { campaignId: string; version: number; disabled: boolean }) {
  useI18n();
  const [layouts, setLayouts] = useState<Layouts | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load(create = false) {
    if (create && (disabled || busy)) return;
    setBusy(true); setError("");
    try {
      const result = await req<Layouts>(`/v1/campaigns/${campaignId}/layouts`, create ? {
        method: "POST", body: JSON.stringify({ expectedVersion: version }),
      } : undefined);
      if (result.version !== version) { setLayouts(null); throw Error(tr("Campaign changed. Reload the campaign before preparing images.")); }
      setLayouts(result);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not prepare campaign images.")); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [campaignId, version]);
  const ready = layouts?.version === version && layouts.state === "ready";
  return <View style={{ gap: 12 }}>
    <Text>{tr("Campaign images · version {v0}", { v0: version })}</Text>
    <Text>{tr("Prepare story and feed images from the saved offer and approved photo. No credits are spent and no video is generated.")}</Text>
    {disabled && <Text>{tr("Save your changes before preparing images.")}</Text>}
    {ready && (["story", "feed"] as const).map(kind => layouts.outputs[kind]
      ? <LayoutPreview key={`${version}-${kind}`} kind={kind} output={layouts.outputs[kind]!} />
      : <Text key={kind}>{tr("This image is unavailable. Refresh and try again.")}</Text>)}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {ready && <CampaignVideoEdit key={`${campaignId}-${version}-${layouts.outputs.video?.url ?? "new"}`}
      campaignId={campaignId} version={version} disabled={disabled || busy} existing={layouts.outputs.video} />}
    {!ready && <Button label={tr("Prepare story and feed images")} disabled={disabled || busy} loading={busy} onPress={() => void load(true)} />}
    <Button label={tr("Refresh campaign images")} variant="ghost" disabled={busy} onPress={() => void load()} />
  </View>;
}
