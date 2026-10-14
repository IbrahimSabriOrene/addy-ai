import { useI18n, translate } from "@/i18n";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, req } from "@/api/client";
import { View, Pressable, ScrollView } from "react-native";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { jobRoute } from "@/lib/jobStatus";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { useTheme } from "@/theme/ThemeProvider";
import { useDecision, useJob } from "@/api/hooks";
import { CandidateVideo } from "@/components/CandidateVideo";
import { ResultPhoto } from "@/components/ResultPhoto";

/**
 * The budget-decision gate (BUILD_BRIEF §3): shown when the auto-regen budget
 * is spent. Presented as a bottom sheet over a dimmed backdrop.
 */
export default function DecisionScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id: string }>();
  const job = useJob(id ?? "");
  const decide = useDecision(id ?? "");
  const [saved, setSaved] = useState<{ action: "accept" | "spend_more" | "abort"; expectedVersion: number; key?: string } | null>(null);
  const [closing, setClosing] = useState(false);
  const [storageKey, setStorageKey] = useState("");
  const [error, setError] = useState("");
  const sending = useRef(false);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const account = await api.getAccount();
        const key = `addy:decision:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${id}`;
        const raw = await AsyncStorage.getItem(key);
        const restored = raw ? JSON.parse(raw) : null;
        if (restored && (!["accept", "spend_more", "abort"].includes(restored.action) || !Number.isInteger(restored.expectedVersion) || restored.expectedVersion < 1 || (restored.key !== undefined && (typeof restored.key !== "string" || !restored.key || restored.key.length > 200)))) throw Error("Saved decision could not be read.");
        if (active) { setSaved(restored); setStorageKey(key); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Could not load saved decision."); }
    })();
    return () => { active = false; };
  }, [id]);

  const candidate = job.data?.exports?.[0];

  const act = async (action: "accept" | "spend_more" | "abort") => {
    if (!storageKey || sending.current || (!saved && !job.data?.version)) return;
    sending.current = true;
    setError("");
    try {
      const command = saved ?? { action, expectedVersion: job.data!.version!, key: `decision-${Date.now()}-${Math.random().toString(36).slice(2)}` };
      setSaved(command);
      await writeAccountDraft(storageKey, JSON.stringify(command));
      const res = await decide.mutateAsync(command);
      await AsyncStorage.removeItem(storageKey);
      if (command.action === "abort") router.replace("/home");
      else if (command.action === "spend_more") router.replace(`/create/generating?id=${id}`);
      else router.replace(`/create/result?id=${res.id}`);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not apply the saved decision."); }
    finally { sending.current = false; }
  };

  async function closeSaved() {
    if (!saved || !storageKey || sending.current) return;
    sending.current = true; setClosing(true); setError("");
    try {
      const result = await req<{ id?: string; state: string }>(`/v1/jobs/${id}/decision/close`, {
        method: "POST", headers: { "Idempotency-Key": saved.key ?? `decision-${id}-${saved.expectedVersion}` },
        body: JSON.stringify({ action: saved.action, expectedVersion: saved.expectedVersion }),
      });
      if (result.state === "cancelled") {
        const current = await job.refetch();
        if (current.isError || !current.data?.version) throw Error("Request closed. Reload the generation before choosing again.");
        await AsyncStorage.removeItem(storageKey);
        setSaved(null); decide.reset();
      } else if (result.id && ["aborted", "submitted", "delivered"].includes(result.state)) {
        await AsyncStorage.removeItem(storageKey);
        if (result.state === "aborted") router.replace("/home");
        else if (result.state === "submitted") router.replace(`/create/generating?id=${result.id}`);
        else if (result.state === "delivered") router.replace(`/create/result?id=${result.id}`);
        else throw Error("Unexpected decision result. Reload the generation.");
      } else throw Error("Could not verify the saved decision.");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not check the saved decision."); }
    finally { sending.current = false; setClosing(false); }
  }

  if (storageKey && !saved && job.data?.campaignId && jobRoute(job.data).startsWith("/create/campaign-result?")) {
    return <Redirect href={jobRoute(job.data)} />;
  }
  return (
    <View style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.72)" }}>
      {/* tap backdrop to cancel */}
      <Pressable style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} onPress={() => router.back()} />

      <ScrollView
        style={{
          maxHeight: "100%",
          flexGrow: 0,
          backgroundColor: t.colors.bgElevated,
          borderTopLeftRadius: t.radius.sheet,
          borderTopRightRadius: t.radius.sheet,
          borderTopWidth: 1,
          borderColor: t.colors.borderSubtle,
        }}
        contentContainerStyle={{ paddingHorizontal: t.space.screenX, paddingTop: Math.max(insets.top, 14), paddingBottom: insets.bottom + 24, alignItems: "center" }}
      >
        <View style={{ width: 42, height: 5, borderRadius: 3, backgroundColor: t.colors.textFaint, marginBottom: 22 }} />
        <Text variant="title" center>
          {translate("Happy with this one?")}</Text>
        <Text variant="bodySm" center color={t.colors.textSecondary} style={{ marginTop: 6, maxWidth: 290 }}>
          {translate("Review this generation before continuing. Starting another generation costs 1 credit.")}</Text>

        {candidate ? (job.data?.outputKind === "photo"
          ? <View style={{ width: "100%", height: 240, marginTop: 16 }}><ResultPhoto url={candidate.url} /></View>
          : <CandidateVideo url={candidate.url} />) :
          <Text accessibilityRole="alert">{translate("No candidate is available to review. Reload the generation.")}</Text>}

        {/* Actions */}
        <View style={{ width: "100%", gap: 11, marginTop: 26 }}>
          {saved ? <><Button label={translate("Retry saved decision: {decision}", { decision: translate(saved.action === "accept" ? "Accept this one" : saved.action === "abort" ? "Cancel" : "Spend 1 credit to retry") })} disabled={!storageKey || decide.isPending || closing} onPress={() => act(saved.action)} />
          <Button label={translate("Check request before choosing again")} variant="secondary" disabled={decide.isPending || closing} onPress={() => void closeSaved()} /></> : <>
          <Button label={translate("Accept this one")} disabled={!storageKey || !job.data?.version || !candidate} loading={decide.isPending} onPress={() => act("accept")} />
          <Button
            variant="secondary"
            label={translate("Spend 1 credit to retry")}
            disabled={!storageKey || !job.data?.version || decide.isPending}
            onPress={() => act("spend_more")}
            trailing={
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 5, backgroundColor: t.colors.accentTintStrong, borderRadius: t.radius.pill }}>
                <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: t.colors.accent }} />
                <Text variant="caption" color={t.colors.accent}>
                  −1
                </Text>
              </View>
            }
          />
          <Pressable accessibilityRole="button" disabled={!storageKey || !job.data?.version || decide.isPending} onPress={() => act("abort")} style={{ minHeight: 44, justifyContent: "center" }}>
            <Text variant="buttonSm" center color={t.colors.textSecondary}>
              {translate("Cancel")}</Text>
          </Pressable>
          </>}
          {!!error && <Text accessibilityRole="alert">{translate(error)}</Text>}
          {decide.isError && <Text accessibilityRole="alert">{translate("Could not apply this decision. Retry the same decision, or reload to review the current generation.")}</Text>}
          {(decide.isError || !job.data?.version) && <Button label={translate("Reload generation")} variant="secondary" onPress={() => job.refetch()} />}
        </View>
      </ScrollView>
    </View>
  );
}
