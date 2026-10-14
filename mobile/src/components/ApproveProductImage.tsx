import { translate as tr, useI18n } from "@/i18n";
import React, { useEffect, useState } from "react";
import { Image, View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { ApiError, req, uploadImage } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";
import { ProductPreview } from "./ProductPreview";

type ApprovedImage = { assetKey: string; version: number };

export function ApproveProductImage({ productId, sourceAssetKey }: { productId: string; sourceAssetKey: string }) {
  useI18n();
  const [current, setCurrent] = useState<ApprovedImage | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uri, setUri] = useState("");
  const [uploaded, setUploaded] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setBusy(true); setError(""); setLoaded(false);
    try {
      const result = await req<{ image: ApprovedImage | null }>(`/v1/products/${productId}/approved-image`);
      setCurrent(result.image); setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load the approved image.")); }
    finally { setBusy(false); }
  }

  useEffect(() => { void load(); }, [productId]);

  async function pick() {
    setBusy(true); setError("");
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
      if (!result.canceled) { setUri(result.assets[0].uri); setUploaded(""); }
    } catch { setError(tr("Could not open your photo library.")); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!loaded || busy) return;
    setBusy(true); setError("");
    try {
      const assetKey = uri ? uploaded || await uploadImage(uri) : current?.assetKey || sourceAssetKey;
      setUploaded(assetKey);
      const image = await req<ApprovedImage>(`/v1/products/${productId}/approved-image`, {
        method: "POST", body: JSON.stringify({ assetKey, expectedVersion: current?.version ?? 0 }),
      });
      setCurrent(image); setUri(""); setUploaded("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setLoaded(false);
      setError(e instanceof Error ? e.message : tr("Could not approve the image."));
    } finally { setBusy(false); }
  }

  return <View style={{ gap: 12 }}>
    {loaded && <>
      <Text>{current ? tr("Approved image · version {version}", { version: current.version }) : tr("Review your product photo")}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
        <View style={{ flex: 1, minWidth: 120 }}><Text>{tr("Original product")}</Text><ProductPreview assetKey={sourceAssetKey} /></View>
        <View style={{ flex: 1, minWidth: 120 }}><Text>{tr("Campaign image")}</Text>
      {uri ? <Image source={{ uri }} accessibilityLabel={tr("Replacement product photo awaiting approval")} resizeMode="contain" style={{ width: "100%", height: 180 }} />
        : <ProductPreview assetKey={current?.assetKey || sourceAssetKey} />}
        </View>
      </View>
      <Text>{tr("Check that the product, label and details are accurate. Approval reuses this photo as-is; it does not clean it or spend credits. Replacing it leaves existing campaigns unchanged.")}</Text>
      <Button label={uri ? tr("Choose another replacement") : tr("Choose replacement photo")} variant="secondary" disabled={busy} onPress={() => void pick()} />
      {(!current || !!uri) && <Button label={tr("Approve this photo for campaigns")} loading={busy} disabled={busy} onPress={() => void approve()} />}
      {!!uri && <Button label={tr("Cancel replacement")} variant="ghost" disabled={busy} onPress={() => { setUri(""); setUploaded(""); }} />}
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {!loaded && <Button label={tr("Reload approved image")} loading={busy} disabled={busy} onPress={() => void load()} />}
  </View>;
}
