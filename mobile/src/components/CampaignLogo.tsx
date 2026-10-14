import { translate as tr, useI18n } from "@/i18n";
import React, { useRef, useState } from "react";
import { View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { uploadImage } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { ProductPreview } from "./ProductPreview";

export function CampaignLogo({ assetKey, disabled, onChange, onBusyChange, context = "campaign" }: {
  context?: "campaign" | "brand";
  assetKey?: string | null; disabled: boolean;
  onChange: (key: string | null) => void; onBusyChange: (busy: boolean) => void;
}) {
  useI18n();
  const sending = useRef(false);
  const [error, setError] = useState("");
  async function pick() {
    if (disabled || sending.current) return;
    sending.current = true; onBusyChange(true); setError("");
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
      if (!result.canceled && result.assets[0]) onChange(await uploadImage(result.assets[0].uri));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not upload your logo.")); }
    finally { sending.current = false; onBusyChange(false); }
  }
  return <View style={{ gap: 12 }}>
    <Text>{context === "brand" ? tr("Brand logo (optional)") : tr("Campaign logo (optional)")}</Text>
    {assetKey && <ProductPreview assetKey={assetKey} />}
    <Text>{tr("Use a logo you own or have permission to use. Save the {v0} to apply your selection.", { v0: context === "brand" ? tr("Brand profile") : tr("Campaign") })}</Text>
    <Button label={tr("{v0} {v1} logo", { v0: assetKey ? tr("Replace") : tr("Choose"), v1: context === "brand" ? tr("Brand") : tr("Campaign") })} disabled={disabled} variant="secondary" onPress={() => void pick()} />
    {assetKey && <Button label={tr("Remove {v0} logo", { v0: context === "brand" ? tr("Brand") : tr("Campaign") })} disabled={disabled} variant="ghost" onPress={() => onChange(null)} />}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View>;
}
