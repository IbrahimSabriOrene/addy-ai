import { translate as tr, useI18n } from "@/i18n";
import React, { useState } from "react";
import { Switch, TextInput, View } from "react-native";
import { router } from "expo-router";
import * as Clipboard from "expo-clipboard";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { useTheme } from "@/theme/ThemeProvider";

type Outcome = { published: boolean; channel: "instagram" | "tiktok" | "facebook" | "other"; messages: number | null; orders: number | null; useful: boolean | null };
export function CampaignPublishing({ campaignId, jobId, resultVersion }: { campaignId: string; jobId: string; resultVersion: string }) {
  useI18n();
  const t = useTheme(), [open, setOpen] = useState(false), [outcome, setOutcome] = useState<Outcome | null>(null);
  const [version, setVersion] = useState(0), [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [link, setLink] = useState("");
  async function load() {
    setBusy(true); setMessage("");
    try { const saved = await req<{ result: Outcome; version: number }>(`/v1/campaigns/${campaignId}/outcome`); setOutcome(saved.result); setVersion(saved.version); }
    catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  async function save() {
    if (!outcome || busy) return;
    setBusy(true); setMessage("");
    try { const saved = await req<{ version: number }>(`/v1/campaigns/${campaignId}/outcome`, { method: "PUT", body: JSON.stringify({ ...outcome, expectedVersion: version }) }); setVersion(saved.version); setMessage(tr("Your results were saved. These are your own observations, not verified attribution.")); }
    catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  return <View style={{ gap: 8 }}>
    <Button label={open ? tr("Close publishing tools") : tr("Publish, measure & use again")} variant="secondary" onPress={() => { setOpen(!open); if (!open && !outcome) void load(); }} />
    {open && <>
      <Text>{tr("Use the vertical video/story for vertical placements, or the square feed image for a square post. Review the destination app's crop, caption and sound before publishing.")}</Text>
      <Text>{tr("Downloading or opening a share sheet does not confirm publication.")}</Text>
      <TextInput accessibilityLabel={tr("Destination link")} placeholder="https://your-store.example/product" value={link} onChangeText={setLink} autoCapitalize="none" maxLength={2000} style={{ color: t.colors.text, padding: 12, borderColor: t.colors.borderStrong, borderWidth: 1 }} />
      <Button label={tr("Copy campaign tracking link")} variant="secondary" onPress={() => {
        void (async () => { try { const url = new URL(link); if (url.protocol !== "https:" || url.username || url.password) throw Error(tr("Enter an HTTPS store link without login details.")); url.searchParams.set("utm_source", outcome?.channel ?? "instagram"); url.searchParams.set("utm_medium", "social"); url.searchParams.set("utm_campaign", `addy-${campaignId}`); await Clipboard.setStringAsync(url.toString()); setMessage(tr("Link copied. Your store analytics must support UTM parameters to measure visits.")); } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } })();
      }} />
      {outcome && <>
        <Text>{tr("Results you observed · totals for this campaign")}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", minHeight: 44 }}><Text style={{ flex: 1 }}>{tr("I published this campaign")}</Text><Switch accessibilityLabel={tr("Published campaign")} value={outcome.published} onValueChange={published => setOutcome({ ...outcome, published })} /></View>
        {(["instagram", "tiktok", "facebook", "other"] as const).map(channel => <Button key={channel} label={channel === "other" ? tr("Other") : channel} variant={outcome.channel === channel ? "selected" : "secondary"} onPress={() => setOutcome({ ...outcome, channel })} />)}
        {(["messages", "orders"] as const).map(field => <View key={field}><Text>{tr("{v0} (leave blank if unknown)", { v0: field === "messages" ? tr("Messages") : tr("Orders") })}</Text><TextInput accessibilityLabel={tr("Campaign {v0}", { v0: field === "messages" ? tr("Messages") : tr("Orders") })} keyboardType="number-pad" value={outcome[field] === null ? "" : String(outcome[field])} maxLength={8} onChangeText={value => { if (/^\d*$/.test(value)) setOutcome({ ...outcome, [field]: value === "" ? null : Number(value) }); }} style={{ color: t.colors.text, padding: 12, borderWidth: 1, borderColor: t.colors.borderStrong }} /></View>)}
        <Button label={outcome.useful === true ? tr("Marked useful") : tr("This campaign was useful")} variant={outcome.useful === true ? "selected" : "secondary"} onPress={() => setOutcome({ ...outcome, useful: outcome.useful === true ? null : true })} />
        <Button label={outcome.useful === false ? tr("Marked not useful") : tr("This campaign was not useful")} variant={outcome.useful === false ? "selected" : "secondary"} onPress={() => setOutcome({ ...outcome, useful: outcome.useful === false ? null : false })} />
        <Button label={tr("Save observed results")} disabled={busy} onPress={() => void save()} />
      </>}
      <Button label={tr("Reload saved results")} variant="ghost" disabled={busy} onPress={() => void load()} />
      <Button label={tr("Renew campaign with a new offer")} variant="secondary" onPress={() => router.push({ pathname: "/create/campaign-copy", params: { campaign: campaignId } })} />
      <Button label={tr("Choose a weekly reminder")} variant="secondary" onPress={() => router.push("/notifications")} />
      <Button label={tr("Copy support reference")} variant="ghost" onPress={() => { void Clipboard.setStringAsync(`Addy AI campaign ${campaignId}; job ${jobId}; result version ${resultVersion}`).then(() => setMessage(tr("Reference copied. Include it if you contact support."))).catch(() => setMessage(tr("Could not copy reference."))); }} />
      <Button label={tr("Get help for this result")} variant="ghost" onPress={() => router.push({ pathname: "/create/report", params: { id: jobId, version: resultVersion } })} />
      {!!message && <Text accessibilityRole="alert">{tr(message)}</Text>}
    </>}
  </View>;
}
