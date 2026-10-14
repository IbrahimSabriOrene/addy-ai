import { translate as tr, useI18n } from "@/i18n";
import { ProductListRow } from "@/components/ProductListRow";
import { DemoProducts } from "@/components/DemoControls";
import React, { useEffect, useState } from "react";
import { TextInput, View } from "react-native";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { req, USE_MOCK } from "@/api/client";
import { useTheme } from "@/theme/ThemeProvider";
import { SaveProduct } from "@/components/SaveProduct";
import { ApproveProductImage } from "@/components/ApproveProductImage";
import { ProductCampaigns } from "@/components/ProductCampaigns";
import { useRouter } from "expo-router";

type Product = { id: string; name: string; description: string; assetKey: string };
type Page = { items: Product[]; nextCursor: string | null };

export default function ProductsScreen() {
  useI18n();
  const router = useRouter();
  const t = useTheme();
  const [adding, setAdding] = useState(false);
  const [options, setOptions] = useState<string | null>(null);
  const [items, setItems] = useState<Product[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [campaigns, setCampaigns] = useState<string | null>(null);

  async function load(next?: string) {
    if (USE_MOCK) return;
    setBusy(true);
    setError("");
    try {
      const page = await req<Page>(`/v1/products${next ? `?cursor=${encodeURIComponent(next)}` : ""}`);
      setItems(previous => next ? [...previous, ...page.items] : page.items);
      setCursor(page.nextCursor);
      setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not load products.")); }
    finally { setBusy(false); }
  }

  async function change(id: string, remove: boolean) {
    setBusy(true);
    setError("");
    try {
      await req(`/v1/products/${id}`, { method: remove ? "DELETE" : "PATCH",
        ...(remove ? {} : { body: JSON.stringify({ name: name.trim() }) }) });
      setEditing(null);
      setDeleting(null);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not update product.")); }
    finally { setBusy(false); }
  }

  useEffect(() => { void load(); }, []);
  if (USE_MOCK) return <DemoProducts />;
  return <Screen bottomInset={24}>
    <TopBar title={tr("My Products")} />
    {USE_MOCK ? <Text>{tr("Sign in with the connected app to view your saved products.")}</Text> : <>
      <Button label={tr("Add product")} onPress={() => setAdding(!adding)} />
      {adding && <><SaveProduct onSaved={() => { setAdding(false); void load(); }} /><Button label={tr("Cancel")} variant="ghost" onPress={() => setAdding(false)} /></>}
      <Button label={tr("Refresh")} variant="ghost" loading={busy} onPress={() => void load()} />
      {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
      {loaded && !busy && !error && !items.length && <Text>{tr("No saved products yet. Products you save will appear here.")}</Text>}
      {items.map(product => <View key={product.id} style={{ padding: 12, marginTop: 12, gap: 12, borderRadius: 18, backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.border }}>
        <ProductListRow name={product.name} onOpen={() => router.push({ pathname: "/product", params: { id: product.id } })} expanded={options === product.id} onOptions={() => { setOptions(options === product.id ? null : product.id); setEditing(null); setDeleting(null); }} />
        {options === product.id && <>
        {!!product.description && <Text>{product.description}</Text>}
        <Button label={tr("Create campaign")} onPress={() => router.push({ pathname: "/create/browse", params: { product: product.id } })} />
        <Button label={campaigns === product.id ? tr("Close campaign history") : tr("Campaign history")} variant="secondary" onPress={() => setCampaigns(campaigns === product.id ? null : product.id)} />
        {campaigns === product.id && <ProductCampaigns key={product.id} productId={product.id} />}
        <Button label={reviewing === product.id ? tr("Close photo review") : tr("Review campaign photo")} variant="secondary" disabled={busy} onPress={() => setReviewing(reviewing === product.id ? null : product.id)} />
        {reviewing === product.id && <ApproveProductImage key={product.id} productId={product.id} sourceAssetKey={product.assetKey} />}
        {editing === product.id ? <>
          <TextInput accessibilityLabel={tr("Product name")} value={name} onChangeText={setName} maxLength={100}
            style={{ color: t.colors.text, borderWidth: 1, borderColor: t.colors.borderStrong, padding: 12 }} />
          <Button label={tr("Save name")} disabled={busy || !name.trim()} onPress={() => void change(product.id, false)} />
          <Button label={tr("Cancel")} variant="ghost" onPress={() => setEditing(null)} />
        </> : <Button label={tr("Rename")} variant="secondary" disabled={busy} onPress={() => { setEditing(product.id); setName(product.name); }} />}
        {deleting === product.id ? <>
          <Text>{tr("Remove this product from My Products? Its original and approved photos, existing campaigns and already-started generations are retained. To request removal of your account data and media, use Delete account in Account.")}</Text>
          <Button label={tr("Remove product")} disabled={busy} onPress={() => void change(product.id, true)} />
          <Button label={tr("Keep product")} variant="ghost" onPress={() => setDeleting(null)} />
        </> : <Button label={tr("Delete")} variant="ghost" disabled={busy} onPress={() => setDeleting(product.id)} />}
        </>}
      </View>)}
      {!!cursor && <Button label={tr("Load more")} loading={busy} onPress={() => void load(cursor)} />}
    </>}
  </Screen>;
}
