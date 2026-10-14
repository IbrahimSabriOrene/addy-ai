import { useI18n, translate } from "@/i18n";
import React, { useState } from "react";
import { Platform, View } from "react-native";
import { exportPrivateMedia } from "@/lib/exportPrivateMedia";
import { Button } from "./Button";
import { Text } from "./Text";
import { trackEngagement } from "@/lib/engagement";

export function ShareMedia({ url, filename, mimeType, onMedia = false }: {
  url: string; filename: string; mimeType: "image/png" | "image/jpeg" | "image/webp" | "video/mp4" | "video/webm"; onMedia?: boolean;
}) {
  useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function share() {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      if (Platform.OS !== "web") {
        await exportPrivateMedia(url, filename, mimeType);
        void trackEngagement("export");
        return;
      }
      if (!navigator.share || !navigator.canShare) {
        setMessage("This browser cannot share files to apps. Download the file, then add it in Instagram or your preferred app.");
        return;
      }
      if (!file) {
        const prepared = await exportPrivateMedia(url, filename, mimeType, "prepare-share");
        if (!prepared || !navigator.canShare({ files: [prepared] })) {
          setMessage("This browser cannot share this file type. Download it and add it in your preferred app.");
          return;
        }
        setFile(prepared);
        setMessage("Your file is ready. Tap Choose app to open sharing.");
        return;
      }
      // A fresh tap preserves browser user activation after a slow download.
      await navigator.share({ files: [file] });
      void trackEngagement("export");
      setMessage("Returned from sharing. Finish and confirm your post in the app you selected.");
    } catch (error) {
      setMessage((error as { name?: string }).name === "AbortError"
        ? "Sharing cancelled. You can try again or download the file."
        : "Could not open sharing. Try again, or download the file and add it in your preferred app.");
    } finally { setBusy(false); }
  }
  return <View style={{ gap: 8 }}>
    <Button label={file ? translate("Choose app") : translate("Share to apps")} loading={busy} disabled={busy || !url} onPress={() => void share()} />
    {!!message && <Text accessibilityLiveRegion="polite" color={onMedia ? "#fff" : undefined}>{translate(message)}</Text>}
  </View>;
}
