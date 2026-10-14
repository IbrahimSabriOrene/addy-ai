import { useI18n, translate } from "@/i18n";
import { ProductListRow } from "./ProductListRow";
import React, { useState } from "react";
import { TextInput, View } from "react-native";
import { useRouter, type Href } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { Screen } from "./Screen";
import { TopBar } from "./TopBar";
import { Button } from "./Button";
import { Text } from "./Text";
import { useTheme } from "@/theme/ThemeProvider";
import { MOCK_CREATION_MEDIA, MOCK_WALLET } from "@/api/mock";

// Preview state only; never used by connected-account requests.
export const demoProducts = [{ id: "demo-mug", name: "Ceramic mug" }];
let demoPermission = false;

export function DemoCredits({ returnTarget }: { returnTarget: Href | null }) {
  useI18n();
  const router = useRouter();
  const queries = useQueryClient();
  const [balance, setBalance] = useState(MOCK_WALLET.balance);
  const [selected, setSelected] = useState(3);
  const [message, setMessage] = useState("");
  return <Screen bottomInset={24}>
    <TopBar title={translate("Demo credits")} fallbackHref="/account" />
    <View style={{ gap: 16, marginTop: 20 }}>
      <Text>{translate("Try the credit flow for free. These are demo credits, not a store purchase. Preview changes reset when the app reloads.")}</Text>
      <Text accessibilityLiveRegion="polite">{translate("Balance:")} {balance} {translate("demo credits")}</Text>
      {[3, 14, 75].map(amount => <Button key={amount} label={translate("{count} demo credits", { count: amount }) + (selected === amount ? translate(" · Selected") : "")} variant={selected === amount ? "selected" : "secondary"} onPress={() => setSelected(amount)} />)}
      <Button label={translate("Add {count} demo credits · free", { count: selected })} onPress={() => {
        MOCK_WALLET.balance += selected;
        setBalance(MOCK_WALLET.balance);
        void queries.invalidateQueries({ queryKey: ["wallet"] });
        setMessage(translate("{count} demo credits added. No payment was taken.", { count: selected }));
      }} />
      <Button label={translate("Restore purchases")} variant="secondary" onPress={() => setMessage("Demo restore completed. There are no real purchases to restore; your demo balance is unchanged.")} />
      <Button label={translate("Refresh balance and purchases")} variant="ghost" onPress={() => { setBalance(MOCK_WALLET.balance); setMessage("Demo balance refreshed. No real purchases."); }} />
      {!!message && <Text accessibilityLiveRegion="polite">{translate(message)}</Text>}
      <Button label={returnTarget ? translate("Return to draft") : translate("Back to account")} variant="secondary" onPress={() => router.replace(returnTarget ?? "/account")} />
    </View>
  </Screen>;
}

export function DemoProducts() {
  useI18n();
  const router = useRouter();
  const t = useTheme();
  const [items, setItems] = useState([...demoProducts]);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [options, setOptions] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const close = () => { setAdding(false); setEditing(null); setName(""); };
  const save = () => {
    if (!name.trim()) return;
    if (editing) { const item = demoProducts.find(p => p.id === editing); if (item) item.name = name.trim(); }
    else demoProducts.push({ id: `demo-${Date.now()}`, name: name.trim() });
    setItems([...demoProducts]); close(); setOptions(null);
  };
  const form = <View style={{ gap: 10, paddingVertical: 12 }}>
    <Text variant="subheading">{editing ? translate("Rename product") : translate("New product")}</Text>
    <TextInput accessibilityLabel={translate("Product name")} placeholder={translate("e.g. Linen tote")} placeholderTextColor={t.colors.textMuted} value={name} onChangeText={setName} maxLength={100}
      style={{ color: t.colors.text, padding: 14, borderRadius: 12, borderWidth: 1, borderColor: t.colors.borderStrong }} />
    <Button label={editing ? translate("Save name") : translate("Save demo product")} disabled={!name.trim()} onPress={save} />
    <Button label={translate("Cancel")} variant="ghost" onPress={close} />
  </View>;
  return <Screen bottomInset={24}>
    <TopBar title={translate("My Products")} fallbackHref="/home" />
    <View style={{ gap: 16, marginTop: 20 }}>
      <Button label={translate("Add product")} onPress={() => { close(); setAdding(true); setOptions(null); setRemoving(null); }} />
      {adding && form}
      {!items.length && <Text>{translate("No products yet. Add your first product to get started.")}</Text>}
      {items.map(item => <View key={item.id} style={{ padding: 12, borderRadius: 18, backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.border }}>
        <ProductListRow name={item.name} photo={item.id === "demo-mug" ? MOCK_CREATION_MEDIA.job_1.photo : undefined}
          onOpen={() => router.push({ pathname: "/product", params: { id: item.id } })} expanded={options === item.id}
          onOptions={() => { close(); setRemoving(null); setOptions(options === item.id ? null : item.id); }} />
        {options === item.id && <View style={{ gap: 8 }}>
          {editing === item.id ? form : <Button label={translate("Rename")} variant="ghost" onPress={() => { setEditing(item.id); setName(item.name); }} />}
          {removing === item.id ? <>
            <Text>{translate("Remove {name} from your products?", { name: item.name })}</Text>
            <Button label={translate("Remove product")} onPress={() => { const index = demoProducts.findIndex(p => p.id === item.id); if (index >= 0) demoProducts.splice(index, 1); setItems([...demoProducts]); setRemoving(null); setOptions(null); close(); }} />
            <Button label={translate("Keep product")} variant="ghost" onPress={() => setRemoving(null)} />
          </> : <Button label={translate("Delete")} variant="ghost" onPress={() => { close(); setRemoving(item.id); }} />}
        </View>}
      </View>)}
      <Text variant="caption" color={t.colors.textMuted}>{translate("Demo · Products reset when you reload.")}</Text>
    </View>
  </Screen>;
}

export function DemoSharing() {
  useI18n();
  const [granted, setGranted] = useState(demoPermission);
  const [message, setMessage] = useState("");
  return <Screen bottomInset={24}>
    <TopBar title={translate("AI sharing")} fallbackHref="/account" />
    <View style={{ gap: 16, marginTop: 20 }}>
      <Text>{translate("Demo only: try the permission controls. No media is sent to an AI provider and this is not a real consent record.")}</Text>
      <Text accessibilityLiveRegion="polite">{granted ? translate("Demo permission granted") : translate("Demo permission not granted")}</Text>
      <Button label={granted ? translate("Withdraw permission") : translate("Allow AI processing")} onPress={() => { demoPermission = !granted; setGranted(demoPermission); setMessage("Demo choice updated for this preview session."); }} />
      {!granted && <Button label={translate("Do not allow")} variant="secondary" onPress={() => setMessage("AI sharing remains off. No media was sent.")} />}
      <Button label={translate("Refresh permission")} variant="ghost" onPress={() => { setGranted(demoPermission); setMessage("Demo permission refreshed."); }} />
      {!!message && <Text accessibilityLiveRegion="polite">{translate(message)}</Text>}
    </View>
  </Screen>;
}
