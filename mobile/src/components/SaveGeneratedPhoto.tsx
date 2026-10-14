import { translate as tr, useI18n } from "@/i18n";
import React, { useState } from "react";
import { ScrollView, View } from "react-native";
import { useRouter } from "expo-router";
import { req } from "@/api/client";
import { useTheme } from "@/theme/ThemeProvider";
import { Button } from "./Button";
import { Text } from "./Text";

type Product = { id: string; name: string };
export function SaveGeneratedPhoto({ jobId, resultVersion, platform }: { jobId: string; resultVersion: string; platform: string }) {
  useI18n();
  const router = useRouter();
  const t = useTheme();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Product[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selection, setSelection] = useState<{ product: Product; version: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  async function load(next?: string) {
    setBusy(true); setError(""); setOpen(true); setSelection(null); setSaved(false);
    try {
      const page = await req<{ items: Product[]; nextCursor: string | null }>(`/v1/products${next ? `?cursor=${encodeURIComponent(next)}` : ""}`);
      setItems(previous => next ? [...previous, ...page.items] : page.items); setCursor(page.nextCursor);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load products.")); }
    finally { setBusy(false); }
  }
  async function select(product: Product) {
    setBusy(true); setError("");
    try {
      const current = await req<{ image: { version: number } | null }>(`/v1/products/${product.id}/approved-image`);
      setSelection({ product, version: current.image?.version ?? 0 });
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load the approved image.")); }
    finally { setBusy(false); }
  }
  async function approve() {
    if (!selection || busy) return;
    setBusy(true); setError("");
    try {
      const asset = await req<{ assetKey: string }>(`/v1/jobs/${jobId}/photo-asset`, {
        method: "POST", body: JSON.stringify({ expectedResultVersion: resultVersion, platform }),
      });
      await req(`/v1/products/${selection.product.id}/approved-image`, {
        method: "POST", body: JSON.stringify({ assetKey: asset.assetKey, expectedVersion: selection.version }),
      });
      setSaved(true);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not save the photo.")); }
    finally { setBusy(false); }
  }
  return <ScrollView style={{ maxHeight: 270, backgroundColor: t.colors.bg, borderRadius: 12 }} contentContainerStyle={{ gap: 8, padding: 12 }}>
    {!open ? <Button label={tr("Use photo for a saved product")} variant="secondary" disabled={busy} onPress={() => void load()} /> : <>
      {saved ? <>
        <Text>{tr("Photo approved for {v0}. Future campaigns can reuse it.", { v0: selection?.product.name ?? "" })}</Text>
        <Button label={tr("My Products")} onPress={() => router.push("/products")} />
      </> : selection ? <>
        <Text>{tr("Approve this photo for {v0}?", { v0: selection.product.name })}</Text>
        <Text>{tr("Check the product, label and details in the photo above. This replaces the campaign photo without spending credits. The original photo and past campaigns stay saved.")}</Text>
        <Button label={tr("Approve this photo for campaigns")} loading={busy} disabled={busy} onPress={() => void approve()} />
        <Button label={tr("Choose product again")} variant="ghost" disabled={busy} onPress={() => void load()} />
      </> : <>
        <Text>{tr("Choose a saved product")}</Text>
        <ScrollView style={{ maxHeight: 160 }} contentContainerStyle={{ gap: 8 }}>
          {items.map(product => <Button key={product.id} label={product.name} variant="secondary" disabled={busy} onPress={() => void select(product)} />)}
          {!!cursor && <Button label={tr("More products")} disabled={busy} onPress={() => void load(cursor)} />}
        </ScrollView>
        {!busy && !items.length && <Button label={tr("Save a product in My Products first")} onPress={() => router.push("/products")} />}
        <Button label={tr("Refresh products")} variant="ghost" loading={busy} disabled={busy} onPress={() => void load()} />
      </>}
      {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
      <Button label={tr("Close photo approval")} variant="ghost" disabled={busy} onPress={() => setOpen(false)} />
    </>}
  </ScrollView>;
}
