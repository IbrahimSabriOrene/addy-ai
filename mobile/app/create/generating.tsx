import { useI18n, translate } from "@/i18n";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { jobRoute } from "@/lib/jobStatus";
import { ActivityIndicator, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { Glow } from "@/components/Glow";
import { useTheme } from "@/theme/ThemeProvider";
import { pollJob, ApiError, AuthError } from "@/api/client";
import type { Job } from "@/api/types";

const STATUS: Record<string, string> = {
  submitted: "Waiting to start…", running: "Creating your result…",
  validating: "Checking your photo…", cleaning: "Preparing your photo…",
  planning: "Preparing your direction…", generating: "Creating your result…",
  composing: "Preparing the layout…", reviewing: "Checking your result…",
  delivering: "Saving your result…", delivered: "Your result is ready.",
};

const STAGE: Record<string, string> = {
  planning: "Preparing your creative direction…",
  input_review: "Preparing and checking your input…",
  generating: "Generation requested. Waiting for the result…",
  generated: "Generation finished. Preparing your output…",
  composed: "Layout prepared. Checking your result…",
  reviewed: "Result reviewed. Finalizing delivery…",
};

export default function GeneratingScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [snapshot, setSnapshot] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const startPolling = useCallback(() => {
    abortRef.current?.abort();
    if (!id) { setError("No generation was selected."); return; }
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    pollJob(id, job => { if (!controller.signal.aborted) setSnapshot(job); }, { signal: controller.signal })
      .then(job => {
        if (controller.signal.aborted) return;
        if (job.campaignId && jobRoute(job).startsWith("/create/campaign-result?")) router.replace(jobRoute(job));
        else if (job.state === "needs_reshoot") router.replace(`/create/reshoot?id=${id}`);
        else if (job.state === "awaiting_style_choice") router.replace(`/create/style?id=${id}`);
        else if (job.state === "awaiting_user_decision") router.replace(`/create/decision?id=${id}`);
        else if (job.state === "delivered") router.replace(`/create/result?id=${id}`);
        else if (job.state === "aborted") setError("This generation was cancelled.");
        else if (job.state === "failed") setError(job.failure?.message ?? "This generation failed. Check your library for its status.");
        else setError("Your result is not ready yet. Check its status again.");
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        if (err instanceof AuthError) { router.replace({ pathname: "/sign-in", params: { returnTo: `/create/generating?id=${encodeURIComponent(id)}` } }); return; }
        setError(err instanceof ApiError && err.code === "poll_timeout"
          ? "Still waiting for your result. You can check again or return to your library."
          : "Could not check the status. Check again when you’re connected.");
      });
  }, [id, router]);

  useEffect(() => {
    startPolling();
    return () => abortRef.current?.abort();
  }, [startPolling]);

  const photo = snapshot && "outputKind" in snapshot && snapshot.outputKind === "photo";
  return <Screen contentStyle={{ alignItems: "center", gap: 24 }} bottomInset={24}
    backgroundLayer={<Glow color="#0f2e2a" cy="30%" rx="130%" ry="80%" fadeEnd={0.55} />}>
    <Text variant="eyebrow" color={t.colors.accent}>{photo ? translate("Creating your product photo") : translate("Creating your ad")}</Text>
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 24, paddingVertical: 48 }}>
      {!error && <ActivityIndicator size="large" color={t.colors.accent} accessibilityLabel={translate("Checking generation status")} />}
      <Text variant="heading" center accessibilityLiveRegion="polite" accessibilityRole={error ? "alert" : undefined}>
        {translate(error ?? (snapshot ? (snapshot.state === "running" && snapshot.stage ? STAGE[snapshot.stage] : undefined) ?? STATUS[snapshot.state] ?? "Checking your generation…" : "Loading generation status…"))}
      </Text>
      {!!error && !!id && <Button label={translate("Check status again")} onPress={startPolling} style={{ minWidth: 200 }} />}
    </View>
    <Text center color={t.colors.textSecondary}>{translate("You can leave this screen and return to your result from the library. Checking status does not start another generation.")}</Text>
    <Button variant="secondary" label={translate("Go to library")} onPress={() => router.replace("/library")} style={{ width: "100%" }} />
  </Screen>;
}
