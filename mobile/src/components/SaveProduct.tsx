import { translate as tr, useI18n } from "@/i18n";
import React, { useState } from "react";
import { Image, TextInput, View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { Button } from "./Button";
import { Text } from "./Text";
import { req, uploadImage } from "@/api/client";
import { useTheme } from "@/theme/ThemeProvider";

export function SaveProduct({ onSaved }: { onSaved: () => void }) {
  useI18n();
  const t = useTheme();
  const [uri, setUri] = useState("");
  const [name, setName] = useState("");
  const [assetKey, setAssetKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function pick() {
    setError("");
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
      if (!result.canceled) { setUri(result.assets[0].uri); setAssetKey(""); }
    } catch { setError(tr("Could not open your photo library.")); }
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      const key = assetKey || await uploadImage(uri);
      setAssetKey(key);
      await req("/v1/products", { method: "POST", headers: { "Idempotency-Key": `product-${key}` }, body: JSON.stringify({ name: name.trim(), assetKey: key }) });
      setUri(""); setName(""); setAssetKey("");
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not save this product.")); }
    finally { setBusy(false); }
  }

  return <View style={{ gap: 12, paddingVertical: 16 }}>
    <Button label={uri ? tr("Choose another photo") : tr("Add product photo")} variant="secondary" disabled={busy} onPress={() => void pick()} />
    {!!uri && <>
      <Image source={{ uri }} accessibilityLabel={tr("Selected product photo")} style={{ width: "100%", height: 180, resizeMode: "contain" }} />
      <TextInput accessibilityLabel={tr("Name your product")} placeholder={tr("Name your product")} placeholderTextColor={t.colors.textSecondary}
        value={name} onChangeText={setName} maxLength={100} editable={!busy}
        style={{ padding: 12, color: t.colors.text, borderColor: t.colors.borderStrong, borderWidth: 1 }} />
      <Text>{tr("Save this photo privately for future campaigns. Saving does not generate an ad or spend credits.")}</Text>
      <Button label={tr("Save this product")} loading={busy} disabled={!name.trim() || busy} onPress={() => void save()} />
    </>}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View>;
}
