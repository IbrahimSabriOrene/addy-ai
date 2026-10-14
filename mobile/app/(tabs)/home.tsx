import { useI18n, translate } from "@/i18n";
import { useQueryClient } from "@tanstack/react-query";
import { getCatalogue } from "@/api/creation";
import { HomeProducts } from "@/components/HomeProducts";
import React, { useCallback, useEffect } from "react";
import { View, Pressable, StyleSheet, Image } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useFocusEffect, useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { PlatformDot } from "@/components/Chips";
import { MediaPlaceholder } from "@/components/MediaPlaceholder";
import { Spinner } from "@/components/Spinner";
import { Play } from "@/components/Icons";
import { TAB_BAR_HEIGHT } from "@/components/TabBar";
import { useTheme } from "@/theme/ThemeProvider";
import { useAccount, useJobs, useWallet } from "@/api/hooks";
import { USE_MOCK } from "@/api/client";
import { MOCK_CREATION_MEDIA } from "@/api/mock";
import type { Job } from "@/api/types";
import { jobRoute, JOB_STATE_LABELS } from "@/lib/jobStatus";

export default function HomeScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  useEffect(() => {
    router.prefetch("/create/browse");
    void queryClient.fetchQuery({ queryKey: ["catalogue"], queryFn: getCatalogue, staleTime: 300000 }).then(data => {
      for (const item of data.items.slice(0, 8)) if (item.poster) void Image.prefetch(item.poster).catch(() => {});
    }).catch(() => {});
  }, [queryClient, router]);
  const account = useAccount();
  const wallet = useWallet();
  const jobs = useJobs();
  useFocusEffect(useCallback(() => { void jobs.refetch(); }, [jobs.refetch]));

  const recent: Job[] = (jobs.data ?? []).slice(0, 4);
  const firstName = account.data?.name?.split(/['\s]/)[0] ?? "Studio";

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <Screen bottomInset={TAB_BAR_HEIGHT}>
      {/* Greeting + credits */}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 16, justifyContent: "space-between", alignItems: "center", paddingTop: 8 }}>
        <View style={{ flexShrink: 1 }}>
          <Text variant="body" color={t.colors.textSecondary}>
            {translate(greeting)}
          </Text>
          <Text variant="display" style={{ marginTop: 2 }}>
            {firstName}
          </Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={translate("Buy credits. {status}", { status: wallet.isError ? translate("Balance unavailable") : wallet.data ? translate("{count} credits available", { count: wallet.data.balance }) : translate("Loading balance…") })}
          onPress={() => router.push("/paywall")}
          style={({ pressed }) => ({
            minHeight: 44, maxWidth: "100%", paddingHorizontal: 16, paddingVertical: 12,
            borderRadius: t.radius.lg, borderWidth: 1, borderColor: t.colors.accentBorder,
            backgroundColor: t.colors.accentTint, opacity: pressed ? 0.75 : 1, gap: 4,
          })}
        >
          <Text variant="subheading">{translate("Credits")}</Text>
          {wallet.isError ? <Text variant="bodySm" accessibilityRole="alert">{translate("Balance unavailable")}</Text>
            : wallet.data ? <Text variant="bodySm" color={t.colors.textSecondary}>{wallet.data.balance} {translate("available")}</Text>
            : <Text variant="bodySm" accessibilityLiveRegion="polite">{translate("Loading balance…")}</Text>}
          <Text variant="buttonSm" color={t.colors.accent}>{translate("Buy credits +")}</Text>
        </Pressable>
      </View>

      {/* Hero CTA */}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={translate("Browse styles for video ads and product photos")}
        onPress={() => router.push("/create/browse")}
        style={{
          marginTop: 22,
          borderRadius: t.radius.hero,
          padding: 24,
          backgroundColor: t.colors.accent,
          overflow: "hidden",
          shadowColor: t.colors.accent,
          shadowOpacity: 0.3,
          shadowRadius: 40,
          shadowOffset: { width: 0, height: 16 },
          elevation: 6,
        }}
      >
        <View
          style={{
            position: "absolute",
            right: -30,
            top: -30,
            width: 150,
            height: 150,
            borderRadius: 75,
            backgroundColor: "rgba(255,255,255,0.12)",
          }}
        />
        <Text variant="title" color={t.colors.accentInk} style={{ maxWidth: 200 }}>
          {translate("Create a product ad")}</Text>
        <Text variant="bodySm" color="rgba(4,32,28,0.72)" style={{ marginTop: 6, maxWidth: 220 }}>
          {translate("Browse styles for video ads and product photos.")}</Text>
        <View
          style={{
            marginTop: 20,
            alignSelf: "flex-start",
            flexDirection: "row",
            alignItems: "center",
            gap: 9,
            paddingHorizontal: 18,
            paddingVertical: 12,
            backgroundColor: t.colors.accentInk,
            borderRadius: t.radius.md + 1,
          }}
        >
          <Play size={13} color={t.brand.tealNeon} />
          <Text variant="buttonSm" color="#fff">
            {translate("Start")}</Text>
        </View>
      </Pressable>

      <HomeProducts />

      {/* Recent */}
      <Text variant="subheading" style={{ marginTop: 30 }}>
        {translate("Recent creations")}</Text>

      {recent.length === 0 ? (
        <EmptyRecent />
      ) : (
        <View style={{ marginTop: 16, flexDirection: "row", flexWrap: "wrap", gap: 14 }}>
          {recent.map((job) => (
            <RecentCard key={job.id} job={job} onPress={() => router.push(jobRoute(job))} />
          ))}
        </View>
      )}
    </Screen>
  );
}

function EmptyRecent() {
  useI18n();
  const t = useTheme();
  return (
    <View
      style={{
        marginTop: 16,
        borderWidth: 1.5,
        borderStyle: "dashed",
        borderColor: t.colors.border,
        borderRadius: t.radius.card,
        paddingVertical: 40,
        paddingHorizontal: 24,
        alignItems: "center",
        gap: 12,
      }}
    >
      <View
        style={{
          width: 56,
          height: 56,
          borderRadius: t.radius.lg,
          backgroundColor: t.colors.surfaceRaised,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <View style={{ width: 20, height: 26, borderWidth: 2, borderColor: t.colors.borderStrong, borderRadius: 5 }} />
      </View>
      <Text variant="subheading">{translate("No creations yet")}</Text>
      <Text variant="bodySm" center color={t.colors.textMuted} style={{ maxWidth: 230 }}>
        {translate("Your product photos and video ads will appear here for review.")}</Text>
    </View>
  );
}

function RecentCard({ job, onPress }: { job: Job; onPress: () => void }) {
  useI18n();
  const t = useTheme();
  const w = "47%";
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${job.title}, ${translate(job.campaignId ? "Campaign pack" : job.outputKind === "photo" ? "Photo" : "Video")}, ${translate(JOB_STATE_LABELS[job.state])}`} onPress={onPress} style={{ width: w }}>
      <MediaPlaceholder
        source={job.id.startsWith("edit_") && job.sourceImage ? {uri:job.sourceImage} : USE_MOCK ? (job.sourceImage ? { uri: job.sourceImage } : MOCK_CREATION_MEDIA[job.id as keyof typeof MOCK_CREATION_MEDIA]?.photo) : undefined}
        label={USE_MOCK ? job.title : translate("Preview unavailable")}
        tone={job.state === "needs_reshoot" ? "warn" : "teal"}
        style={{ width: "100%", aspectRatio: 9 / 13, borderRadius: t.radius.xl }}
      >
        {/* Lifecycle labels reflect recorded state without invented percentages. */}
        {job.state === "generating" || job.state === "running" || job.state === "submitted" ? (
          <View style={[StyleSheet.absoluteFill, { alignItems: "center", justifyContent: "center", backgroundColor: "rgba(14,14,17,0.4)" }]}>
            <Spinner size={26} color={t.colors.warning} />
            <Text family={t.fonts.display} color={t.colors.warningText} style={{ marginTop: 8, fontSize: 13 }}>
              {translate(JOB_STATE_LABELS[job.state])}
            </Text>
          </View>
        ) : null}

        <View style={{ position: "absolute", top: 10, left: 10, flexDirection: "row", gap: 4 }}>
          {job.platforms.slice(0, 2).map((p) => (
            <PlatformDot key={p} platform={p} />
          ))}
        </View>

        <View
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            paddingHorizontal: 10,
            paddingVertical: 9,
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
          }}
        >
          <LinearGradient
            colors={["transparent", "rgba(0,0,0,0.75)"]}
            style={StyleSheet.absoluteFill}
            pointerEvents="none"
          />
          {job.state === "generating" && (
            <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.colors.warning }} />
          )}
          <Text variant="caption" family={t.fonts.displayMed} color="#fff" numberOfLines={1} style={{ flex: 1 }}>
            {job.title}
          </Text>
        </View>
      </MediaPlaceholder>
    </Pressable>
  );
}
