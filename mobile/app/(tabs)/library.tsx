import { useI18n, translate, getLocale } from "@/i18n";
import React, { useCallback, useState } from "react";
import { View, Pressable } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { PlatformDot } from "@/components/Chips";
import { Button } from "@/components/Button";
import { MediaPlaceholder } from "@/components/MediaPlaceholder";
import { Spinner } from "@/components/Spinner";
import { Download, Play } from "@/components/Icons";
import { TAB_BAR_HEIGHT } from "@/components/TabBar";
import { useTheme } from "@/theme/ThemeProvider";
import { useLibraryJobs } from "@/api/hooks";
import { USE_MOCK } from "@/api/client";
import { MOCK_CREATION_MEDIA } from "@/api/mock";
import type { Job } from "@/api/types";
import { isJobPending, JOB_STATE_LABELS, jobRoute } from "@/lib/jobStatus";

const FILTERS = ["All", "Delivered", "In progress"] as const;

export default function LibraryScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const jobs = useLibraryJobs();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  useFocusEffect(useCallback(() => { void jobs.refetch(); }, [jobs.refetch]));

  const loaded: Job[] = jobs.data?.pages.flatMap(page => page.items) ?? [];
  const list = loaded.filter(j =>
    filter === "All" ? true : filter === "Delivered" ? j.state === "delivered" : isJobPending(j)
  );

  return (
    <Screen bottomInset={TAB_BAR_HEIGHT}>
      <Text variant="display" style={{ paddingTop: 4 }}>
        {translate("Your library")}</Text>

      {/* Filter chips */}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
        {FILTERS.map((f) => {
          const active = f === filter;
          return (
            <Pressable
              key={f}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              aria-pressed={active}
              onPress={() => setFilter(f)}
              style={{
                minHeight: 44,
                justifyContent: "center",
                paddingHorizontal: 14,
                paddingVertical: 8,
                borderRadius: t.radius.pill,
                backgroundColor: active ? "#302844" : t.colors.surfaceRaised,
                borderWidth: 1, borderColor: active ? "#BCA3F5" : t.colors.border,
              }}
            >
              <Text variant="label" family={active ? t.fonts.bodyBold : t.fonts.bodySemi} color={active ? "#E4D8FF" : t.colors.textSecondary} style={{ fontSize: 12.5 }}>
                {translate(f)}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Rows */}
      <Button label={translate("Refresh library")} variant="ghost" loading={jobs.isRefetching} onPress={() => void jobs.refetch()} />
      {jobs.isPending && <Text>{translate("Loading your library…")}</Text>}
      {jobs.isError && <Text accessibilityRole="alert">{translate(jobs.error.message)}</Text>}
      {!jobs.isPending && !jobs.isError && !list.length && <Text>{loaded.length ? (filter === "In progress" && !jobs.hasNextPage ? translate("No creations in progress. Finished creations are in Delivered.") : translate("No matching creations.")) : translate("Your library is empty. Create a product photo or video to begin.")}</Text>}
      <View style={{ marginTop: 18, gap: 12 }}>
        {list.map((job) => (
          <LibraryRow key={job.id} job={job} onPress={() => router.push(jobRoute(job))} />
        ))}
      </View>
      {jobs.hasNextPage && <Button label={translate("Load older results")} variant="secondary" loading={jobs.isFetchingNextPage} onPress={() => void jobs.fetchNextPage()} style={{ marginTop: 20 }} />}
    </Screen>
  );
}

function LibraryRow({ job, onPress }: { job: Job; onPress: () => void }) {
  useI18n();
  const t = useTheme();
  const isGenerating = isJobPending(job);
  const isReshoot = job.state === "needs_reshoot";

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${job.title}, ${translate(job.campaignId ? "Campaign pack" : job.outputKind === "photo" ? "Photo" : "Video")}, ${translate(JOB_STATE_LABELS[job.state] ?? job.state)}`}
      style={{
        flexDirection: "row",
        gap: 13,
        alignItems: "center",
        padding: 11,
        borderRadius: t.radius.xl,
        backgroundColor: t.colors.surface,
        borderWidth: 1,
        borderColor: t.colors.borderSubtle,
      }}
    >
      <MediaPlaceholder
        source={job.id.startsWith("edit_") && job.sourceImage ? {uri:job.sourceImage} : USE_MOCK ? (job.sourceImage ? { uri: job.sourceImage } : MOCK_CREATION_MEDIA[job.id as keyof typeof MOCK_CREATION_MEDIA]?.photo) : undefined}
        label={USE_MOCK ? job.title : translate("Preview unavailable")}
        tone={isReshoot ? "warn" : "teal"}
        style={{ width: 56, height: 74, borderRadius: t.radius.md }}
      >
        {isGenerating ? (
          <Spinner size={18} />
        ) : isReshoot ? (
          <View style={{ width: 20, height: 20, borderRadius: 10, backgroundColor: t.colors.warning, alignItems: "center", justifyContent: "center" }}>
            <Text family={t.fonts.display} color="#2a1500" style={{ fontSize: 13 }}>
              !
            </Text>
          </View>
        ) : (
          <View style={{ position: "absolute", bottom: 6, width: 18, height: 18, borderRadius: 9, backgroundColor: "rgba(255,255,255,0.8)", alignItems: "center", justifyContent: "center" }}>
            <Play size={9} color={t.colors.accentInk} />
          </View>
        )}
      </MediaPlaceholder>

      <View style={{ flex: 1, minWidth: 0 }}>
        <Text variant="cardTitle" numberOfLines={1}>
          {job.title}
        </Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 5 }}>
          {job.platforms.slice(0, 3).map((p) => (
            <PlatformDot key={p} platform={p} />
          ))}
          <Text variant="label" family={t.fonts.bodyReg} color={t.colors.textMuted} style={{ marginLeft: 2 }}>
            {relTime(job.createdAt)}
          </Text>
        </View>
        <View style={{ marginTop: 7 }}>
          <Text variant="label" color={t.colors.textSecondary}>{job.campaignId ? translate("Campaign pack") : job.outputKind === "photo" ? translate("Photo") : translate("Video")} · {translate(JOB_STATE_LABELS[job.state] ?? job.state)}</Text>
        </View>
      </View>

      {job.state === "delivered" && (
        <View style={{ width: 38, height: 38, borderRadius: t.radius.md, backgroundColor: t.colors.surfaceRaisedStrong, alignItems: "center", justifyContent: "center" }}>
          <Download size={17} color={t.colors.text} strokeWidth={2} />
        </View>
      )}
      {isReshoot && (
        <View style={{ height: 34, paddingHorizontal: 13, borderRadius: 11, backgroundColor: t.colors.accentTintStrong, alignItems: "center", justifyContent: "center" }}>
          <Text variant="label" family={t.fonts.display} color={t.colors.accent} style={{ fontSize: 12.5 }}>
            {translate("Retry")}</Text>
        </View>
      )}
    </Pressable>
  );
}

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const h = diff / 3600e3;
  if (h < 1) return new Intl.RelativeTimeFormat(getLocale(), { numeric: "auto" }).format(-Math.max(1, Math.round(diff / 60e3)), "minute");
  if (h < 24) return new Intl.RelativeTimeFormat(getLocale(), { numeric: "auto" }).format(-Math.round(h), "hour");
  const d = Math.round(h / 24);
  return new Intl.RelativeTimeFormat(getLocale(), { numeric: "auto" }).format(-d, "day");
}
