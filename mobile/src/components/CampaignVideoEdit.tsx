import { translate as tr, useI18n } from "@/i18n";
import React, { useRef, useState } from "react";
import { View } from "react-native";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { CampaignMediaPreview } from "./CampaignMediaPreview";
import { ExportMedia } from "./ExportMedia";

type Video = { url: string; offer: string; cta: string; sourceVersion: number };

export function CampaignVideoEdit({ campaignId, version, disabled, existing }: {
  campaignId: string; version: number; disabled: boolean; existing?: Video;
}) {
  useI18n();
  const [video, setVideo] = useState(existing);
  const [sources, setSources] = useState<number[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const api = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/v1\/?$/, "");
  async function act(sourceVersion?: number, more = false) {
    if (sending.current || disabled) return;
    sending.current = true; setBusy(true); setError("");
    try {
      if (sourceVersion === undefined) {
        const result = await req<{ items: { version: number; jobState: string }[]; nextBeforeVersion?: number | null }>(
          `/v1/campaigns/${campaignId}/generations?limit=100${more && nextBefore !== null ? `&beforeVersion=${nextBefore}` : ""}`);
        const delivered = result.items.filter(item => item.jobState === "delivered").map(item => item.version);
        const combined = more ? [...new Set([...sources, ...delivered])] : delivered;
        setSources(combined);
        setNextBefore(result.nextBeforeVersion ?? null);
        if (!combined.length) setError(result.nextBeforeVersion ? tr("No delivered videos on this page. Load older videos.") : tr("No delivered videos found."));
      } else {
        const result = await req<{ version: number; outputs: { video?: Video } }>(`/v1/campaigns/${campaignId}/video-layout`, {
          method: "POST", body: JSON.stringify({ expectedVersion: version, sourceVersion }),
        });
        if (result.version !== version || !result.outputs.video) throw Error(tr("Campaign changed. Reload before editing video."));
        setVideo(result.outputs.video);
      }
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not prepare video. Retry the same source.")); }
    finally { sending.current = false; setBusy(false); }
  }
  return <View style={{ gap: 8 }}>
    <Text>{tr("Update video offer · no credits")}</Text>
    <Text>{tr("Update on-screen offer and CTA text using a delivered video. This does not change speech. Its picture and speech must be verified free of old offers; otherwise this edit is unavailable. Any new generation requires its own displayed price and confirmation.")}</Text>
    {video ? <>
      <Text>{video.offer} · {video.cta}</Text>
      <CampaignMediaPreview url={`${api}${video.url}`} video label={tr("Updated campaign video")} />
      <ExportMedia url={`${api}${video.url}`} filename="addy-video.mp4" mimeType="video/mp4" />
    </> : <>
      <Button label={tr("Choose a delivered video")} disabled={disabled || busy} onPress={() => void act()} />
      {sources.map(source => <Button key={source} label={tr("Use video from version {v0}", { v0: source })} disabled={disabled || busy}
        onPress={() => void act(source)} />)}
      {nextBefore !== null && <Button label={tr("Load older videos")} disabled={disabled || busy} onPress={() => void act(undefined, true)} />}
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View>;
}
