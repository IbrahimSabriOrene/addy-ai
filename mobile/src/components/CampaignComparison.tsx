import { translate as tr, useI18n } from "@/i18n";
import React, { useState } from "react";
import { View } from "react-native";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { ProductPreview } from "./ProductPreview";
import { CampaignMediaPreview } from "./CampaignMediaPreview";

export function CampaignComparison({ campaignId, assetKey, url, video }: { campaignId?: string; assetKey?: string; url: string; video: boolean }) {
  useI18n();
  const [original, setOriginal] = useState(""), [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function toggle() {
    if (open) { setOpen(false); return; }
    setBusy(true); setError("");
    try {
      if (assetKey) setOriginal(assetKey);
      else {
        const campaign = await req<{ productId: string }>(`/v1/campaigns/${campaignId}`);
        const product = await req<{ assetKey: string }>(`/v1/products/${campaign.productId}`);
        setOriginal(product.assetKey);
      }
      setOpen(true);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Original product is unavailable.")); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 12 }}>
    <Button label={open ? tr("Close product comparison") : tr("Compare with original product")} variant="secondary" disabled={busy} loading={busy} onPress={() => void toggle()} />
    {open && <>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
        <View style={{ flex: 1, minWidth: 120 }}><Text>{tr("Original product")}</Text><ProductPreview assetKey={original} /></View>
        <View style={{ flex: 1, minWidth: 120 }}><Text>{tr("Campaign result")}</Text><CampaignMediaPreview initiallyOpen url={url} video={video} label={tr("Result to compare")} /></View>
      </View>
      <Text>{tr("Check label text, color, shape and packaging. For video, play with sound and check spoken claims too.")}</Text>
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View>;
}
