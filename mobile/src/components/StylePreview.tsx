import { useI18n, translate } from "@/i18n";
import Svg, { Path } from "react-native-svg";
import React, { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, AppState, Image, Platform, View, Pressable } from "react-native";
import { useIsFocused } from "expo-router";
import { useVideoPlayer, VideoView } from "expo-video";
import { Button } from "./Button";
import { Text } from "./Text";

function WebStyleVideo({ uri, play, muted, onError, aspectRatio, poster }: { uri: string; play: boolean; muted: boolean; onError: () => void; aspectRatio: number; poster?: string }) {
  useI18n();
  const ref = useRef<HTMLVideoElement>(null);
  const [readyUri, setReadyUri] = useState<string | null>(null);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    video.muted = muted;
    if (play) void video.play().catch(() => {});
    else video.pause();
    return () => video.pause();
  }, [play, muted, uri]);
  return <View style={{ width: "100%", aspectRatio, borderRadius: 20, overflow: "hidden" }}>
    {poster && <Image source={{ uri: poster }} accessibilityLabel={translate("Style preview poster")} resizeMode="contain"
      style={{ position: "absolute", width: "100%", height: "100%" }} />}
    {React.createElement("video", { ref, src: uri, poster, loop: true, muted, playsInline: true, preload: play ? "auto" : "metadata", autoPlay: play,
      "aria-label": "Style preview video", onError,
      onPlaying: () => {
        const video = ref.current;
        if (video?.requestVideoFrameCallback) video.requestVideoFrameCallback(() => setReadyUri(uri));
        else setReadyUri(uri);
      },
      style: { position: "absolute", width: "100%", height: "100%", objectFit: "contain", backgroundColor: "transparent", opacity: !poster || readyUri === uri ? 1 : 0 } })}
  </View>;
}

function NativeStyleVideo({ uri, play, muted, onError, aspectRatio, poster }: { uri: string; play: boolean; muted: boolean; onError: () => void; aspectRatio: number; poster?: string }) {
  useI18n();
  const player = useVideoPlayer(uri, value => { value.loop = true; });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    player.muted = muted;
    if (play) player.play(); else player.pause();
    return () => player.pause();
  }, [player, play, muted]);
  useEffect(() => {
    const listener = player.addListener("statusChange", status => { if (status.status === "error") onError(); });
    return () => listener.remove();
  }, [player, onError]);
  return <View style={{ width: "100%", aspectRatio, borderRadius: 20, overflow: "hidden" }}>
    <VideoView onFirstFrameRender={() => setReady(true)} player={player} nativeControls={false} contentFit="contain" accessibilityLabel={translate("Style preview video")}
    style={{ width: "100%", height: "100%" }} />
    {!ready && poster && <Image source={{ uri: poster }} resizeMode="contain" accessibilityLabel={translate("Style preview poster")} style={{ position: "absolute", width: "100%", height: "100%" }} />}
  </View>;
}

export function StylePreview({ uri, mode, active = true, controls = false, compactControls = false, aspectRatio = 4 / 3, poster }: { uri?: string | null; mode: "photo" | "video"; active?: boolean; controls?: boolean; compactControls?: boolean; aspectRatio?: number; poster?: string }) {
  useI18n();
  const focused = useIsFocused();
  const [foreground, setForeground] = useState(AppState.currentState !== "background" && AppState.currentState !== "inactive");
  const [reduced, setReduced] = useState(true);
  const [intent, setIntent] = useState<boolean | null>(null);
  const [muted, setMuted] = useState(true);
  const [error, setError] = useState(false);
  const [photoReady, setPhotoReady] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void AccessibilityInfo.isReduceMotionEnabled().then(value => { if (live) setReduced(value); }).catch(() => {});
    const motion = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduced);
    const state = AppState.addEventListener("change", value => setForeground(value === "active"));
    return () => { live = false; motion.remove(); state.remove(); };
  }, []);
  const eligible = active && focused && foreground;
  useEffect(() => { if (!eligible) { setIntent(null); setMuted(true); } }, [eligible]);
  useEffect(() => { setError(false); setIntent(null); setMuted(true); }, [uri, mode]);
  const play = eligible && (intent ?? !reduced);
  if (!uri || error) return <Text accessibilityRole="alert">{translate("Style preview unavailable")}</Text>;
  if (mode === "photo") return <View style={{ width: "100%", aspectRatio, borderRadius: 20, overflow: "hidden" }}>
    {poster && <Image source={{ uri: poster }} accessibilityLabel={translate("Style preview poster")} resizeMode="contain" style={{ position: "absolute", width: "100%", height: "100%" }} />}
    <Image source={{ uri }} accessibilityLabel={translate("Style preview photo")} resizeMode="contain" onLoad={() => setPhotoReady(uri)}
      onError={() => setError(true)} style={{ width: "100%", height: "100%", opacity: !poster || photoReady === uri ? 1 : 0 }} />
  </View>;
  if (!active && !controls && poster) return <View style={{ width: "100%", aspectRatio, borderRadius: 20, overflow: "hidden" }}>
    <Image source={{ uri: poster }} accessibilityLabel={translate("Style preview poster")} resizeMode="contain" style={{ width: "100%", height: "100%" }} />
  </View>;
  const Video = Platform.OS === "web" ? WebStyleVideo : NativeStyleVideo;
  return <View style={{ gap: 8 }}>
    <Video key={uri} poster={poster} aspectRatio={aspectRatio} uri={uri} play={play} muted={muted} onError={() => setError(true)} />
    {Platform.OS !== "web" && !play && !controls && poster && <Image source={{ uri: poster }} resizeMode="contain" style={{ position: "absolute", top: 0, left: 0, width: "100%", aspectRatio, borderRadius: 20 }} />}
    {controls && compactControls && <View style={{ position: "absolute", bottom: 10, right: 10, flexDirection: "row", gap: 6 }}>
      <Pressable accessibilityRole="button" accessibilityLabel={play ? translate("Pause style preview") : translate("Play style preview")} onPress={() => setIntent(!play)} style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(0,0,0,0.65)", alignItems: "center", justifyContent: "center" }}>
        <Svg width={18} height={18} viewBox="0 0 24 24"><Path fill="#fff" d={play ? "M7 5h3v14H7zM14 5h3v14h-3z" : "M8 5v14l11-7Z"} /></Svg>
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={muted ? translate("Unmute style preview") : translate("Mute style preview")} onPress={() => setMuted(value => !value)} style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(0,0,0,0.65)", alignItems: "center", justifyContent: "center" }}>
        <Svg width={18} height={18} viewBox="0 0 24 24" fill="none"><Path d="M3 9h4l5-4v14l-5-4H3Z" stroke="#fff" strokeWidth={1.8} /><Path d={muted ? "m17 9 5 6m0-6-5 6" : "M16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"} stroke="#fff" strokeWidth={1.8} /></Svg>
      </Pressable>
    </View>}
    {controls && !compactControls && <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      <Button label={play ? translate("Pause style preview") : translate("Play style preview")} variant="secondary" onPress={() => setIntent(!play)} />
      <Button label={muted ? translate("Unmute style preview") : translate("Mute style preview")} variant="secondary" onPress={() => setMuted(value => !value)} />
    </View>}
    {controls && reduced && <Text>{translate("Automatic preview playback is off for reduced motion.")}</Text>}
  </View>;
}
