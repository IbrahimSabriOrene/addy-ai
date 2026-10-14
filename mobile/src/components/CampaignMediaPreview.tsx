import { translate as tr, useI18n } from "@/i18n";
import React, { useState } from "react";
import { Image, Platform, View } from "react-native";
import { useVideoPlayer, VideoView } from "expo-video";
import { usePrivateMedia } from "@/lib/usePrivateMedia";
import { Button } from "./Button";
import { Text } from "./Text";

function NativeCampaignVideo({ source }: { source: { uri: string; headers?: Record<string, string> } }) {
  useI18n();
  const player = useVideoPlayer(source);
  return <VideoView player={player} nativeControls contentFit="contain" accessibilityLabel={tr("Campaign video preview")}
    style={{ width: "100%", aspectRatio: 9 / 16 }} />;
}

function LoadedCampaignPreview({ url, video, label, ratio }: { url: string; video: boolean; label: string; ratio: number }) {
  useI18n();
  const { source, error } = usePrivateMedia(url);
  const [decodeError, setDecodeError] = useState(false);
  if (error || decodeError) return <Text accessibilityRole="alert">{error || tr("This media could not be previewed. Close and reopen the preview to try again.")}</Text>;
  if (!source) return <Text>{tr("Loading preview…")}</Text>;
  if (!video) return <Image source={source} accessibilityLabel={label} resizeMode="contain" onError={() => setDecodeError(true)}
    style={{ width: "100%", aspectRatio: ratio }} />;
  if (Platform.OS === "web") return React.createElement("video", {
    src: source.uri, controls: true, playsInline: true, autoPlay: false, preload: "metadata", "aria-label": label,
    onError: () => setDecodeError(true), style: { width: "100%", aspectRatio: "9 / 16", objectFit: "contain", backgroundColor: "#000" },
  });
  return <NativeCampaignVideo key={source.uri} source={source} />;
}

export function CampaignMediaPreview({ url, video, label, width, height, initiallyOpen = false, guides = false }: { url: string; video: boolean; label: string; width?: number; height?: number; initiallyOpen?: boolean; guides?: boolean }) {
  useI18n();
  const [open, setOpen] = useState(initiallyOpen);
  const [guide, setGuide] = useState(false);
  const ratio = width && height && width > 0 && height > 0 ? width / height : video ? 9 / 16 : 1;
  return <View style={{ gap: 8 }}>
    {open && (!guides ? <LoadedCampaignPreview key={url} url={url} video={video} label={label} ratio={ratio} /> : <>
      <View style={{ position: "relative" }}>
        <LoadedCampaignPreview key={url} url={url} video={video} label={label} ratio={ratio} />
        {guide && <View pointerEvents="none" accessibilityLabel={tr("Illustrative central placement guide")} style={{ position: "absolute", top: "10%", bottom: "25%", left: "10%", right: "18%", borderWidth: 2, borderStyle: "dashed", borderColor: "#ffcc00" }} />}
      </View>
      {guides && <Button label={guide ? tr("Hide placement guide") : tr("Show placement guide")} variant="ghost" onPress={() => setGuide(!guide)} />}
      {guide && <Text>{tr("Illustrative guide only; it does not change your export. Keep key text visible and verify the actual Instagram/TikTok placement preview. Captions, buttons and device layouts change the covered area.")}</Text>}
    </>)}
    <Button label={tr("{v0} {v1}", { v0: open ? tr("Close") : tr("Preview"), v1: label.toLowerCase() })} variant="secondary" onPress={() => setOpen(value => !value)} />
  </View>;
}
