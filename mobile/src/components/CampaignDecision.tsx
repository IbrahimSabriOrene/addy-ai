import { translate as tr, useI18n } from "@/i18n";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import { View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";

type Action = "accept" | "abort" | "spend_more";
type Command = { key: string; body: { action: Action; expectedVersion: number; confirmedCredits?: number } };
type Consent = { granted: boolean; disclosureVersion: string; disclosure: string };

export function CampaignDecision({ jobId, resultVersion, price, complete, onResolved }: {
  jobId: string; resultVersion: string; price: number; complete: boolean; onResolved: () => void;
}) {
  useI18n();
  const [version, setVersion] = useState<number | null>(null);
  const [command, setCommand] = useState<Command | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState<Consent | null>(null);
  const storageKey = useRef("");
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [account, job] = await Promise.all([req<{ email: string }>("/v1/account"), req<{ version: number; resultVersion: string; state: string }>(`/v1/jobs/${jobId}`)]);
        if (job.resultVersion !== resultVersion || job.state !== "awaiting_user_decision") throw Error(tr("The result changed. Refresh the campaign before deciding."));
        const key = `addy:pack-decision:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${jobId}:${job.version}`;
        const saved = await AsyncStorage.getItem(key);
        const restored: Command | null = saved ? JSON.parse(saved) : null;
        if (restored && (restored.body?.expectedVersion !== job.version || !["accept", "abort", "spend_more"].includes(restored.body.action) || typeof restored.key !== "string")) throw Error(tr("Saved decision could not be read."));
        if (active) { storageKey.current = key; setVersion(job.version); setCommand(restored); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : tr("Could not load decision.")); }
      finally { if (active) setBusy(false); }
    })();
    return () => { active = false; };
  }, [jobId, resultVersion]);
  async function decide(action: Action, allow = false) {
    if (busy || version === null || (!command && action === "accept" && !complete)) return;
    setBusy(true); setError("");
    try {
      if (!command && action === "spend_more") {
        if (allow && consent) await req("/v1/account/ai-consent", { method: "PUT", body: JSON.stringify({ granted: true, disclosureVersion: consent.disclosureVersion }) });
        const permission = await req<Consent>("/v1/account/ai-consent");
        if (!permission.granted) { setConsent(permission); return; }
      }
      setConsent(null);
      const pending = command ?? { key: `decision-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        body: { action, expectedVersion: version, ...(action === "spend_more" ? { confirmedCredits: price } : {}) } };
      setCommand(pending);
      await writeAccountDraft(storageKey.current, JSON.stringify(pending));
      await req(`/v1/jobs/${jobId}/decision`, { method: "POST", headers: { "Idempotency-Key": pending.key }, body: JSON.stringify(pending.body) });
      await AsyncStorage.removeItem(storageKey.current);
      onResolved();
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not submit decision. Retry the saved decision.")); }
    finally { setBusy(false); }
  }
  async function closeSavedDecision() {
    if (busy || !command) return;
    setBusy(true); setError("");
    try {
      const result = await req<{ id?: string; state: string }>(`/v1/jobs/${jobId}/decision/close`, {
        method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body),
      });
      if (result.state === "cancelled") {
        const current = await req<{ version: number; resultVersion: string; state: string }>(`/v1/jobs/${jobId}`);
        if (current.version !== version || current.resultVersion !== resultVersion || current.state !== "awaiting_user_decision") {
          setVersion(null); onResolved();
          throw Error(tr("Request closed. Refresh the campaign to review its current result."));
        }
        await AsyncStorage.removeItem(storageKey.current);
        setCommand(null); setConsent(null);
      } else if (result.id === jobId && ["aborted", "submitted", "delivered"].includes(result.state)) {
        await AsyncStorage.removeItem(storageKey.current);
        setVersion(null); onResolved();
      } else throw Error(tr("Could not verify the saved decision."));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not check the saved decision.")); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 12 }}>
    <Text>{tr("Review the campaign before deciding. Accepting spends {v0} reserved credits. Cancel releases them. Trying again releases this hold and reserves {v1} credits for a new attempt.", { v0: price, v1: price })}</Text>
    {command ? <><Button label={tr("Retry saved decision: {v0}", { v0: command.body.action === "accept" ? tr("Accept") : command.body.action === "abort" ? tr("Cancel") : tr("Try again") })} disabled={busy || version === null} loading={busy} onPress={() => void decide(command.body.action)} />
      <Button label={tr("Check request before choosing again")} variant="secondary" disabled={busy} onPress={() => void closeSavedDecision()} /></> : <>
      <Button label={tr("Accept pack · {v0} credits", { v0: price })} disabled={busy || version === null || !complete || !!consent} onPress={() => void decide("accept")} />
      <Button label={tr("Cancel and release credits")} variant="secondary" disabled={busy || version === null || !!consent} onPress={() => void decide("abort")} />
      <Button label={tr("Try again · {v0} credits", { v0: price })} variant="secondary" disabled={busy || version === null || !!consent} onPress={() => void decide("spend_more")} />
    </>}
    {!!consent && <><Text>{tr(consent.disclosure)}</Text>
      <Button label={tr("Allow AI processing and try again")} disabled={busy} onPress={() => void decide("spend_more", true)} />
      <Button label={tr("Do not allow")} variant="secondary" disabled={busy} onPress={() => setConsent(null)} />
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View>;
}
