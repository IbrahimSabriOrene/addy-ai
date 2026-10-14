import { useI18n, translate } from "@/i18n";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { writeAccountDraft } from "@/lib/accountDrafts";
import Svg, { Path } from "react-native-svg";
import { ShareMedia } from "@/components/ShareMedia";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { View, Pressable, ScrollView, ViewStyle, Alert, Platform, Modal, TextInput, KeyboardAvoidingView } from "react-native";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { jobRoute } from "@/lib/jobStatus";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { LinearGradient } from "expo-linear-gradient";
import { VideoView, useVideoPlayer } from "expo-video";
import { Text } from "@/components/Text";
import { Screen, WEB_TOP_INSET } from "@/components/Screen";
import { Button } from "@/components/Button";
import { TopBar } from "@/components/TopBar";
import { PlatformChip } from "@/components/Chips";
import { Check, Copy } from "@/components/Icons";
import { useTheme } from "@/theme/ThemeProvider";
import { useJob, useRegen } from "@/api/hooks";
import { MOCK_RESULT } from "@/api/mock";
import type { PlatformKey, PlatformExport } from "@/api/types";
import { ApiError, req, USE_MOCK } from "@/api/client";
import { exportPrivateMedia } from "@/lib/exportPrivateMedia";
import { ResultPhoto } from "@/components/ResultPhoto";
import { SaveGeneratedPhoto } from "@/components/SaveGeneratedPhoto";
import { CampaignComparison } from "@/components/CampaignComparison";
import { usePrivateMedia } from "@/lib/usePrivateMedia";

export default function ResultScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id: string }>();
  const job = useJob(id ?? "");
  const regen = useRegen(id ?? "");
  const data = job.data ?? MOCK_RESULT;
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [copyNotice, setCopyNotice] = useState("");
  const [panel, setPanel] = useState<"caption" | "more" | null>(null);
  const isPhoto = "outputKind" in data && data.outputKind === "photo";

  const exports: PlatformExport[] = USE_MOCK
    ? (data.exports?.length ? data.exports : MOCK_RESULT.exports ?? []).map(item => ({ ...item, url: item.url || "/mock/sample-ad.mp4" }))
    : data.exports ?? [];
  const [active, setActive] = useState<PlatformKey>(exports[0]?.platform ?? "tiktok");
  const selected = exports.some(e => e.platform === active) ? active : exports[0]?.platform;
  const originalCaption = useMemo(() => exports.find((e: PlatformExport) => e.platform === selected)?.caption ?? "", [selected, exports]);

  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [savedCaption, setSavedCaption] = useState<{ key: string; text: string } | null>(null);
  const [captionKey, setCaptionKey] = useState("");
  const [savingCaption, setSavingCaption] = useState(false);
  const [editError, setEditError] = useState("");
  const captionIdentity = `${id}:${data.resultVersion ?? data.version}:${selected}`;
  const caption = savedCaption?.key === captionIdentity ? savedCaption.text : originalCaption;
  useEffect(() => {
    let alive = true;
    setCaptionKey(""); setEditOpen(false); setEditError("");
    void (async () => {
      try {
        const account = USE_MOCK ? { email: "demo" } : await req<{ email: string }>("/v1/account");
        const key = `addy:create:${process.env.EXPO_PUBLIC_API_URL ?? "demo"}:${account.email}:result-caption:${captionIdentity}`;
        const value = await AsyncStorage.getItem(key);
        if (alive) { setSavedCaption(value === null ? null : { key: captionIdentity, text: value }); setCaptionKey(key); }
      } catch { if (alive) setEditError("Could not load your saved caption. Reopen this result to retry."); }
    })();
    return () => { alive = false; };
  }, [captionIdentity]);

  useEffect(() => { setCopyNotice(""); }, [id, selected, caption]);
  useEffect(() => {
    if (copyNotice !== "copied") return;
    const timer = setTimeout(() => setCopyNotice(""), 2000);
    return () => clearTimeout(timer);
  }, [copyNotice]);

  const onRegen = async () => {
    try {
      if (!job.data?.version) return;
      await regen.mutateAsync(job.data.version);
      router.replace(`/create/generating?id=${id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 403 && err.code === "current_ai_processing_permission_is_required") {
          router.push("/ai-sharing");
        } else if (err.status === 402 || (err.status === 409 && err.code === "insufficient_credits")) {
          router.push("/paywall");
        }
      }
    }
  };

  const activeExport = exports.find((e: PlatformExport) => e.platform === selected);
  const videoUrl = activeExport?.url ?? "";
  const localEdit=id?.startsWith("edit_");
  const mediaMime=activeExport?.mimeType??(isPhoto?"image/png":"video/mp4");
  const extension=mediaMime==="video/webm"?"webm":isPhoto?"png":"mp4";

  const onDownload = async () => {
    if (!videoUrl) {
      Alert.alert("Not ready yet", "Your result will be available after rendering is complete.");
      return;
    }
    if (exporting) return;
    setExporting(true); setExportError("");
    try {
      await exportPrivateMedia(videoUrl, `addy-${selected}.${extension}`, mediaMime);
    } catch (e) { setExportError(e instanceof Error ? e.message : "Could not export this file."); }
    finally { setExporting(false); }
  };

  const copy = async () => {
    setCopyNotice("");
    try {
      if (!(await Clipboard.setStringAsync(caption))) throw new Error("Clipboard copy failed");
      setCopyNotice("copied");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch {
      setCopyNotice("Could not copy the caption. Please try again.");
    }
  };

  if (job.data?.campaignId && jobRoute(job.data).startsWith("/create/campaign-result?")) {
    return <Redirect href={jobRoute(job.data)} />;
  }
  if (!job.data || job.isError || data.state !== "delivered" || !exports.length) {
    return <Screen>
      <TopBar title={translate("Your result")} />
      <Text accessibilityLiveRegion="polite">
        {!id ? translate("No result was selected.") : job.isError ? translate("Could not load this result.") : job.isPending ? translate("Loading your result…") : translate("Your result is not ready yet.")}
      </Text>
      {job.error && <Text accessibilityRole="alert">{translate(job.error.message)}</Text>}
      {!!id && <Button label={translate("Refresh result")} loading={job.isFetching} onPress={() => void job.refetch()} />}
    </Screen>;
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <StatusBar style="light" />

      {isPhoto ? <ResultPhoto url={videoUrl} /> : <ResultVideo url={videoUrl} />}
      {/* Gradient scrim: dark at the very top + bottom, clear through the middle */}
      <LinearGradient
        colors={["rgba(0,0,0,0.55)", "rgba(0,0,0,0)", "rgba(0,0,0,0)", "rgba(0,0,0,0.85)"]}
        locations={[0, 0.22, 0.6, 1]}
        style={StyleAbsFill}
        pointerEvents="none"
      />

      <Modal visible={editOpen} transparent animationType="slide" onRequestClose={() => { if (!savingCaption) setEditOpen(false); }}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.55)" }}>
          <View accessibilityViewIsModal style={{ maxHeight: "85%", backgroundColor: "#171717", borderTopLeftRadius: 26, borderTopRightRadius: 26, padding: 20, paddingBottom: Math.max(insets.bottom, 20), gap: 14 }}>
            <View style={{ width: 36, height: 4, borderRadius: 2, backgroundColor: "#555", alignSelf: "center" }} />
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text variant="heading" color="#fff">{translate("Edit your creation")}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel={translate("Cancel editing")} disabled={savingCaption} onPress={() => setEditOpen(false)} style={{ minHeight: 44, minWidth: 64, justifyContent: "center" }}>
                <Text color="#bbb" center>{translate("Cancel")}</Text>
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 14 }}>
              <Text variant="subheading" color="#fff">{translate("Caption")}</Text>
              <TextInput accessibilityLabel={translate("Edit caption")} multiline maxLength={2200} value={editText} onChangeText={setEditText} editable={!!captionKey && !savingCaption}
                placeholder={translate("Write your caption…")} placeholderTextColor="#999" style={{ color: "#fff", backgroundColor: "#242424", borderRadius: 14, padding: 14, minHeight: 130, textAlignVertical: "top", fontSize: 16, lineHeight: 23 }} />
              <Text variant="caption" color="#aaa">{translate("Saved on this device. Copy it when you share.")}</Text>
              {!!editError && <Text accessibilityRole="alert" color="#ffaaaa">{translate(editError)}</Text>}
              <Button label={translate("Save caption")} loading={savingCaption} disabled={!captionKey || savingCaption} onPress={() => {
                setSavingCaption(true); setEditError("");
                void writeAccountDraft(captionKey, editText).then(() => {
                  setSavedCaption({ key: captionIdentity, text: editText }); setEditOpen(false); setPanel("caption");
                }).catch(() => setEditError("Could not save. Your text is still here; try again.")).finally(() => setSavingCaption(false));
              }} />
              <Button label={translate("Change style")} variant="secondary" disabled={savingCaption} onPress={() => { setEditOpen(false); router.push("/create/browse"); }} />
              <Text variant="caption" color="#aaa">{translate("A new style starts a separate creation. Your current result stays saved.")}</Text>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Top row */}
      <View style={{ position: "absolute", top: Math.max(insets.top, WEB_TOP_INSET) + 4, left: t.space.screenX, right: t.space.screenX }}>
        <TopBar
          onMedia
          right={
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 7,
                paddingHorizontal: 13,
                paddingVertical: 7,
                backgroundColor: "rgba(0,194,168,0.9)",
                borderRadius: t.radius.pill,
              }}
            >
              <Check size={13} color={t.colors.accentInk} />
              <Text variant="label" family={t.fonts.bodyBold} color={t.colors.accentInk} style={{ fontSize: 12 }}>
                {localEdit ? translate("Edited copy") : USE_MOCK ? translate("Demo sample") : isPhoto ? translate("Your photo is ready") : translate("Your ad is ready")}
              </Text>
            </View>
          }
        />
      </View>

      {/* Bottom: platform tabs + caption + actions */}
      <ScrollView style={{ position: "absolute", left: 0, right: 0, bottom: 0, maxHeight: "65%" }}
        showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled" automaticallyAdjustKeyboardInsets
        contentContainerStyle={{ paddingHorizontal: t.space.screenX, paddingBottom: insets.bottom + 16 }}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, marginBottom: 14 }}>
          {exports.map((e: PlatformExport) => (
            <PlatformChip
              key={e.platform}
              platform={e.platform}
              onMedia
              active={e.platform === selected}
              onPress={() => setActive(e.platform)}
            />
          ))}
        </ScrollView>

        <ShareMedia key={`${selected}:${videoUrl}`} url={videoUrl} filename={`addy-${selected}.${extension}`} mimeType={mediaMime} onMedia />
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <Pressable accessibilityRole="button" accessibilityLabel={translate("Edit result")} disabled={!captionKey} accessibilityState={{ disabled: !captionKey }}
            onPress={() => { router.push({ pathname: "/create/editor", params: { id, exportPlatform: selected ?? "" } }); }}
            style={{ flex: 1, minHeight: 44, flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center", backgroundColor: "#242424", borderRadius: 12 }}>
            <Svg width={16} height={16} viewBox="0 0 24 24" fill="none"><Path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15Z" stroke="#fff" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" /></Svg>
            <Text color="#fff">{translate("Edit")}</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel={translate("Caption")} accessibilityState={{ expanded: panel === "caption" }}
            onPress={() => setPanel(panel === "caption" ? null : "caption")} style={{ flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center" }}>
            <Text color="#fff">{translate("Caption")}</Text>
          </Pressable>
          {Platform.OS === "web" && <Pressable accessibilityRole="button" accessibilityLabel={translate("Download result")} disabled={exporting}
            accessibilityState={{ disabled: exporting, busy: exporting }} onPress={onDownload}
            style={{ flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center" }}>
            <Text color="#fff">{exporting ? translate("Saving...") : translate("Download")}</Text>
          </Pressable>}
          <Pressable accessibilityRole="button" accessibilityLabel={translate("More options")} accessibilityState={{ expanded: panel === "more" }}
            onPress={() => setPanel(panel === "more" ? null : "more")} style={{ flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center" }}>
            <Text color="#fff">{translate("More")}</Text>
          </Pressable>
        </View>
        {panel === "caption" && <View style={{ padding: 16, gap: 12, backgroundColor: "#171717", borderRadius: 16 }}>
          <Text color="#fff" style={{ lineHeight: 22 }}>{caption}</Text>
          <Button label={translate("Edit caption")} variant="secondary" disabled={!captionKey} onPress={() => { setEditText(caption); setEditOpen(true); }} />
          <Pressable accessibilityRole="button" accessibilityLabel={translate("Copy caption")} onPress={copy} style={{ alignSelf: "flex-end", minHeight: 44, minWidth: 96, paddingHorizontal: 14, borderRadius: 12, flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", backgroundColor: copyNotice === "copied" ? "#123b33" : "#292929" }}>
            {copyNotice === "copied" ? <Check size={15} color="#55dec0" /> : <Copy size={15} color="#fff" />}
            <Text variant="label" accessibilityLiveRegion="polite" color={copyNotice === "copied" ? "#55dec0" : "#fff"}>{copyNotice === "copied" ? translate("Copied") : translate("Copy")}</Text>
          </Pressable>
        </View>}
        {panel === "more" && <View style={{ padding: 16, gap: 12, backgroundColor: "#171717", borderRadius: 16 }}>
          {!USE_MOCK && !localEdit && data.sourceImage && videoUrl && <CampaignComparison key={`${id}:${videoUrl}`} assetKey={data.sourceImage} url={videoUrl} video={!isPhoto} />}
          {!localEdit && <Pressable accessibilityRole="button" accessibilityLabel={USE_MOCK ? translate("Replay sample - free") : translate("Create another version - 1 credit")}
            accessibilityState={{ disabled: regen.isPending || !job.data?.version, busy: regen.isPending }}
            disabled={regen.isPending || !job.data?.version} onPress={onRegen} style={{ minHeight: 44, justifyContent: "center" }}>
            <Text color="#fff">{regen.isPending ? translate("Starting...") : USE_MOCK ? translate("Replay sample - free") : translate("Create another version - 1 credit")}</Text>
          </Pressable>}
          {!USE_MOCK && !localEdit && isPhoto && id && data.resultVersion && selected && <SaveGeneratedPhoto
            key={`${id}:${data.resultVersion}:${selected}`} jobId={id} resultVersion={data.resultVersion} platform={selected} />}
          {!USE_MOCK && !localEdit && <Pressable accessibilityRole="button" accessibilityLabel={translate("Report this result")}
            onPress={() => router.push({ pathname: "/create/report", params: { id, version: data.resultVersion ?? "" } })} style={{ minHeight: 44, justifyContent: "center" }}>
            <Text color="#fff">{translate("Report this result")}</Text>
          </Pressable>}
          <Text variant="bodySm" color="#b5b5b5">{USE_MOCK ? translate("Demo video, not your uploaded product. ") : ""}{translate("Review product details and claims before posting. Disclose AI use where required.")}</Text>
        </View>}
        {!!copyNotice && copyNotice !== "copied" && <Text accessibilityRole="alert" color="#fff">{translate(copyNotice)}</Text>}
        {!!editError && !editOpen && <Text accessibilityRole="alert" color="#fff">{translate(editError)}</Text>}
        {!!exportError && <Text accessibilityRole="alert" color="#fff">{translate(exportError)}</Text>}
        {regen.isError && <Pressable onPress={() => job.refetch()} accessibilityRole="button" accessibilityLabel={translate("Reload generation")}>
          <Text accessibilityRole="alert" color="#fff">{translate("Could not start another generation. Retry, or tap here to reload its current status.")}</Text>
        </Pressable>}
      </ScrollView>
    </View>
  );
}

const StyleAbsFill = { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 } as const;

function ResultVideo({ url }: { url: string }) {
  useI18n();
  const { source, error } = usePrivateMedia(url);
  if (error) return <Text accessibilityRole="alert">{translate(error)}</Text>;
  if (!url) {
    return <Text accessibilityRole="alert">{translate("Video unavailable. Refresh this result.")}</Text>;
  }
  if (!source) return <Text>{translate("Loading video…")}</Text>;
  if (Platform.OS === "web") return <WebResultVideo key={source.uri} uri={source.uri} />;
  return <NativeResultVideo key={source.uri} source={source} />;
}

function PlaybackActions({ ended, muted, paused, onReplay, onMute, onPause }: { ended: boolean; muted: boolean; paused: boolean; onReplay: () => void; onMute: () => void; onPause: () => void }) {
  useI18n();
  return <View pointerEvents="box-none" style={{ position: "absolute", inset: 0 }}>
    {ended && <View pointerEvents="box-none" style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
      <Pressable accessibilityRole="button" accessibilityLabel={translate("Replay video")} onPress={onReplay} style={{ width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.6)" }}>
        <Svg width={30} height={30} viewBox="0 0 24 24" fill="none"><Path d="M4 10a8 8 0 1 1 1 8M4 4v6h6" stroke="#fff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>
      </Pressable>
    </View>}
    <View style={{ position: "absolute", top: 12, right: 16, flexDirection: "row", gap: 8 }}>
      {!ended && <Pressable accessibilityRole="button" accessibilityLabel={paused ? translate("Resume video") : translate("Pause video")} onPress={onPause} style={{ width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.55)" }}>
        <Svg width={18} height={18} viewBox="0 0 24 24"><Path d={paused ? "M8 5v14l11-7Z" : "M7 5h3v14H7zM14 5h3v14h-3z"} fill="#fff" /></Svg>
      </Pressable>}
      <Pressable accessibilityRole="button" accessibilityLabel={muted ? translate("Unmute video") : translate("Mute video")} onPress={onMute} style={{ width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.55)" }}>
        <Svg width={20} height={20} viewBox="0 0 24 24" fill="none"><Path d="M3 9h4l5-4v14l-5-4H3Z" stroke="#fff" strokeWidth={1.8} strokeLinejoin="round" /><Path d={muted ? "m17 9 5 6m0-6-5 6" : "M16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"} stroke="#fff" strokeWidth={1.8} strokeLinecap="round" /></Svg>
      </Pressable>
    </View>
  </View>;
}

const playerFrame = { position: "absolute", top: 90, bottom: 200, width: "100%" } as const;

function WebResultVideo({ uri }: { uri: string }) {
  useI18n();
  const ref = useRef<HTMLVideoElement>(null);
  const [ended, setEnded] = useState(false);
  const [muted, setMuted] = useState(true);
  const [paused, setPaused] = useState(false);
  const start = () => { setEnded(false); void ref.current?.play().catch(() => setPaused(true)); };
  useEffect(() => { start(); }, [uri]);
  return <View style={playerFrame}>
    {React.createElement("video", { ref, src: uri, autoPlay: true, muted, playsInline: true, controls: false, loop: false,
      onEnded: () => setEnded(true), onPlay: () => setPaused(false), onPause: () => setPaused(true),
      style: { width: "100%", height: "100%", objectFit: "contain", backgroundColor: "#000" } })}
    <PlaybackActions ended={ended} paused={paused} muted={muted}
      onReplay={() => { if (ref.current) ref.current.currentTime = 0; start(); }}
      onMute={() => { if (ref.current) ref.current.muted = !muted; setMuted(!muted); }}
      onPause={() => { if (paused) start(); else ref.current?.pause(); }} />
  </View>;
}

function NativeResultVideo({ source }: { source: { uri: string; headers?: Record<string, string> } }) {
  useI18n();
  const [ended, setEnded] = useState(false);
  const [muted, setMuted] = useState(true);
  const [paused, setPaused] = useState(false);
  const player = useVideoPlayer(source, value => { value.loop = false; value.muted = true; value.play(); });
  useEffect(() => {
    const end = player.addListener("playToEnd", () => setEnded(true));
    const playing = player.addListener("playingChange", event => setPaused(!event.isPlaying));
    return () => { end.remove(); playing.remove(); };
  }, [player]);
  return <View style={playerFrame}>
    <VideoView player={player} nativeControls={false} contentFit="contain" style={{ width: "100%", height: "100%" }} />
    <PlaybackActions ended={ended} paused={paused} muted={muted}
      onReplay={() => { player.currentTime = 0; setEnded(false); player.play(); }}
      onMute={() => { player.muted = !muted; setMuted(!muted); }}
      onPause={() => { if (paused) player.play(); else player.pause(); }} />
  </View>;
}
