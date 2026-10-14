import { useI18n, translate } from "@/i18n";
import { ShareMedia } from "./ShareMedia";
import React, { useState } from "react";
import { Platform, View } from "react-native";
import { exportPrivateMedia } from "@/lib/exportPrivateMedia";
import { Button } from "./Button";
import { Text } from "./Text";
import { trackEngagement } from "@/lib/engagement";

export function ExportMedia({ url, filename, mimeType }: { url: string; filename: string; mimeType: "image/png" | "image/jpeg" | "image/webp" | "video/mp4" }) {
  useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function exportFile() {
    if (busy) return;
    setBusy(true); setError("");
    try { await exportPrivateMedia(url, filename, mimeType); void trackEngagement("export"); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not export this file."); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 8 }}>
    <ShareMedia key={url} url={url} filename={filename} mimeType={mimeType} />
    {Platform.OS === "web" && <Button label={translate(mimeType === "video/mp4" ? "Download video" : "Download image")} variant="secondary" loading={busy} disabled={busy} onPress={() => void exportFile()} />}
    {!!error && <Text accessibilityRole="alert">{translate(error)}</Text>}
  </View>;
}
