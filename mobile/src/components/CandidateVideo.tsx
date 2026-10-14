import { useI18n, translate } from "@/i18n";
import React from "react";
import { Platform } from "react-native";
import { useVideoPlayer, VideoView } from "expo-video";
import { usePrivateMedia } from "@/lib/usePrivateMedia";
import { Text } from "@/components/Text";

export function CandidateVideo({ url }: { url: string }) {
  useI18n();
  const { source, error } = usePrivateMedia(url);
  if (error) return <Text accessibilityRole="alert">{translate(error)}</Text>;
  if (!source) return <Text>{translate("Loading your candidate…")}</Text>;
  if (Platform.OS === "web") return React.createElement("video", {
    src: source.uri, controls: true, playsInline: true, "aria-label": translate("Review your generated video"),
    style: { width: "100%", height: 240, objectFit: "contain", marginTop: 16 },
  });
  return <NativeCandidate key={source.uri} source={source} />;
}

function NativeCandidate({ source }: { source: { uri: string; headers?: Record<string, string> } }) {
  useI18n();
  const player = useVideoPlayer(source);
  return <VideoView player={player} nativeControls contentFit="contain"
    accessibilityLabel={translate("Review your generated video")} style={{ width: "100%", height: 240, marginTop: 16 }} />;
}
