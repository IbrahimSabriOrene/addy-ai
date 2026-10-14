import { translate as tr, useI18n } from "@/i18n";
import React, { useEffect, useState } from "react";
import { AppState, View } from "react-native";
import { router } from "expo-router";
import * as Clipboard from "expo-clipboard";
import { ApiError, req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { ExportMedia } from "./ExportMedia";
import { CampaignMediaPreview } from "./CampaignMediaPreview";
import { CampaignDecision } from "./CampaignDecision";
import { CampaignComparison } from "./CampaignComparison";
import { CampaignPublishing } from "./CampaignPublishing";

type Output = { state: "ready" | "pending" | "unavailable"; url?: string;
  width?: number; height?: number;
  mimeType?: "image/png" | "image/jpeg" | "image/webp" | "video/mp4"; caption?: string; cta?: string };
type Pack = { attemptSequence?: number | null; attempts?: { sequence: number; state: string }[]; campaignId: string; campaignVersion: number; jobId: string; resultVersion: string; priceCredits: number; state: string; outputs: Record<string, Output>; failure?: { code: string; message: string } | null };
const labels = { video: "Video with sound", cleanImage: "Approved product image", story: "Story", feed: "Feed image", copy: "Caption and CTA" };
const extensions = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4" };

export function CampaignResults({ campaignId, version }: { campaignId: string; version: number }) {
  useI18n();
  const [attempt, setAttempt] = useState<number | null>(null);
  const [pack, setPack] = useState<Pack | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [more, setMore] = useState(false);
  const [missing, setMissing] = useState(false);
  const api = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/v1\/?$/, "");
  async function load() {
    setBusy(true); setError(""); setNotice(""); setPack(null); setMissing(false);
    try {
      const result = await req<Pack>(`/v1/campaigns/${campaignId}/generations/${version}${attempt !== null ? `?attempt=${attempt}` : ""}`);
      if (result.campaignId !== campaignId || result.campaignVersion !== version || (attempt !== null && result.attemptSequence !== attempt)) throw Error(tr("Campaign result changed. Refresh and try again."));
      setPack(result);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMissing(true);
      else setError(e instanceof Error ? e.message : tr("Could not load campaign results."));
    } finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [campaignId, version, attempt]);
  useEffect(() => {
    if (!pack || !["submitted", "running"].includes(pack.state)) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      clearTimeout(timer);
      if (AppState.currentState === "active") timer = setTimeout(() => void load(), 5000);
    };
    const subscription = AppState.addEventListener("change", schedule);
    schedule();
    return () => { clearTimeout(timer); subscription.remove(); };
  }, [pack]);
  async function copy(output: Output) {
    try { await Clipboard.setStringAsync([output.caption, output.cta].filter(Boolean).join("\n")); setNotice(tr("Caption and CTA copied.")); }
    catch { setError(tr("Could not copy text.")); }
  }
  return <View style={{ gap: 12 }}>
    <Text>{tr("Campaign pack · version {v0}", { v0: version })}</Text>
    {missing && <Text>{tr("No pack has been generated for this campaign version.")}</Text>}
    {pack && <>
      {attempt !== null && <Text>{tr("Generation attempt {v0} · saved preview. Use the latest result for any credit decisions.", { v0: attempt })}</Text>}
      {!!pack.failure && <Text accessibilityRole="alert">{tr(pack.failure.message)}</Text>}
      <Text>{pack.state === "archived" ? tr("Saved output from this generation attempt.") : pack.state === "delivered" ? tr("Your campaign pack is ready.") : pack.state === "incomplete" ? tr("Some campaign files are unavailable.") : pack.state === "awaiting_user_decision" ? tr("This campaign needs your review.") : pack.state === "failed" ? tr("Campaign generation needs attention.") : pack.state === "aborted" ? tr("Campaign cancelled. Your reserved credits have been released.") : tr("Your campaign is being prepared.")}</Text>
      {Object.entries(labels).map(([kind, label]) => {
        const output = pack.outputs[kind];
        return <View key={kind} style={{ gap: 8 }}>
          <Text>{tr(label)} · {output?.state === "ready" ? tr("Ready") : output?.state === "unavailable" ? tr("Unavailable") : tr("Preparing")}</Text>
          {output?.state === "ready" && (kind === "copy" ? <>
            <Text>{output.caption}</Text><Text>{output.cta}</Text>
            <Button label={tr("Copy pack caption and CTA")} variant="secondary" onPress={() => void copy(output)} />
          </> : output.url && output.mimeType ? <>
            <CampaignMediaPreview initiallyOpen={kind === "video"} guides={kind === "video" || kind === "story"} url={`${api}${output.url}`} video={output.mimeType === "video/mp4"} label={tr(label)} width={output.width} height={output.height} />
            <ExportMedia url={`${api}${output.url}`} filename={`addy-${kind}.${extensions[output.mimeType]}`} mimeType={output.mimeType} />
          </> : null)}
        </View>;
      })}
    <Text variant="bodySm">{tr("AI-created media can change product details. Check claims, prices and rights before publishing, and disclose AI use where required by law or the platform.")}</Text>
      <Button label={tr("More")} variant="secondary" onPress={() => setMore(!more)} />
      {more && <View style={{ gap: 12 }}>
      <Button label={tr("Edit latest campaign")} variant="secondary" onPress={() => router.push({ pathname: "/create/campaign-edit", params: { campaign: campaignId } })} />
      {attempt === null && pack.state === "delivered" && <CampaignPublishing key={pack.resultVersion} campaignId={campaignId} jobId={pack.jobId} resultVersion={pack.resultVersion} />}
      {pack.outputs.video?.state === "ready" && pack.outputs.video.url && <CampaignComparison key={`${pack.resultVersion}-${attempt}`} campaignId={campaignId} url={`${api}${pack.outputs.video.url}`} video />}
      {["delivered", "incomplete", "awaiting_user_decision", "archived"].includes(pack.state) &&
        <Button label={tr("Report this campaign result")} variant="ghost" onPress={() => router.push({ pathname: "/create/report", params: { id: pack.jobId, version: pack.resultVersion, ...(attempt !== null ? { attempt: String(attempt) } : {}) } })} />}
</View>}
      {((pack.attempts?.length ?? 0) > 1 || attempt !== null) && <View style={{ gap: 8 }}>
        <Button label={tr("View latest result")} variant="secondary" disabled={attempt === null || busy} onPress={() => setAttempt(null)} />
        {pack.attempts?.map(item => <Button key={item.sequence} label={tr("View generation attempt {v0}", { v0: item.sequence })} variant="secondary" disabled={attempt === item.sequence || busy} onPress={() => setAttempt(item.sequence)} />)}
      </View>}
      {attempt === null && pack.state === "awaiting_user_decision" && <CampaignDecision key={`${pack.jobId}-${pack.resultVersion}`} jobId={pack.jobId} resultVersion={pack.resultVersion}
        price={pack.priceCredits} complete={Object.keys(labels).every(kind => pack.outputs[kind]?.state === "ready")} onResolved={() => void load()} />}
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{tr(notice)}</Text>}
    <Button label={tr("Refresh campaign pack")} variant="ghost" loading={busy} disabled={busy} onPress={() => void load()} />
  </View>;
}
