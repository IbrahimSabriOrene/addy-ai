import { useI18n } from "@/i18n";
import { USE_MOCK } from "@/api/client";
import { DemoCredits } from "@/components/DemoControls";
import React, { useEffect, useState } from "react";
import { View, Pressable } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { openPublicLink, TERMS_URL } from "@/lib/publicLinks";
import { draftReturn } from "@/lib/draftReturn";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { useTheme } from "@/theme/ThemeProvider";
import { useWallet } from "@/api/hooks";
import { getCreditPacks, getCreditPurchases, type CreditPack, type CreditPurchase } from "@/api/billing";
import { acknowledgePendingPurchase, checkPendingPurchase, readPendingPurchase, getCreditProducts, IAP_CONFIGURED, purchasePack, restorePurchases, type PendingPurchase } from "@/lib/purchases";
import type { PurchasesStoreProduct } from "react-native-purchases";

export default function PaywallScreen() {
  const { tr, locale } = useI18n();
  const t = useTheme();
  const router = useRouter();
  const { returnTo } = useLocalSearchParams<{ returnTo?: string }>();
  const returnTarget = draftReturn(returnTo);
  const wallet = useWallet();
  const [selected, setSelected] = useState("");
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [history, setHistory] = useState<CreditPurchase[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [busy, setBusy] = useState(false);
  const [products, setProducts] = useState<PurchasesStoreProduct[]>([]);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<PendingPurchase | null>(null);
  const [purchaseBlocked, setPurchaseBlocked] = useState(true);
  const [reviewPending, setReviewPending] = useState(false);

  useEffect(() => {
    let active = true;
    getCreditPacks().then(async catalogue => {
      const items = catalogue.length ? await getCreditProducts(catalogue.map(p => p.productId)) : [];
      if (active) {
        setPacks(catalogue);
        setProducts(items);
        const firstPack = catalogue.find(pack => items.some(item => item.identifier === pack.productId));
        if (firstPack) setSelected(firstPack.productId);
        if (!items.length) setMessage("No credit packs are available in your store.");
      }
    }).catch(error => { if (active) setMessage(error.message); });
    getCreditPurchases().then(items => { if (active) setHistory(items); })
      .catch(() => { if (active) setHistoryError("Purchase history unavailable. Try refreshing."); });
    readPendingPurchase().then(value => { if (active) { setPending(value); setPurchaseBlocked(!!value); } })
      .catch(() => { if (active) setMessage("Could not check saved purchases. Refresh before buying."); });
    return () => { active = false; };
  }, []);

  const pack = packs.find(p => p.productId === selected);
  const product = products.find(p => p.identifier === selected);

  const refresh = async () => {
    try {
      const value = await checkPendingPurchase();
      setPending(value);
      setPurchaseBlocked(!!value);
    } catch { setPurchaseBlocked(true); setMessage("Purchase confirmation unavailable. Your saved checkout is retained; try refreshing later."); }
    await wallet.refetch();
    try { setHistory(await getCreditPurchases()); setHistoryError(""); }
    catch { setHistoryError("Purchase history unavailable. Try refreshing."); }
  };

  const buy = async () => {
    if (busy || purchaseBlocked || !product || !pack) return;
    setBusy(true);
    setMessage("");
    try {
      const current = (await getCreditPacks()).find(item => item.productId === pack.productId);
      if (!current || current.credits !== pack.credits) {
        setMessage("Credit packs changed. Reopen this screen before purchasing.");
        setProducts([]);
        return;
      }
      await purchasePack(pack.productId);
      await refresh();
      setMessage("Store checkout completed. Credits appear after server confirmation. Check your balance before buying again.");
    } catch (error) {
      setMessage((error as { userCancelled?: boolean }).userCancelled
        ? "Purchase cancelled."
        : "Purchase could not be confirmed. Check your balance before trying again.");
    } finally {
      try { const value = await readPendingPurchase(); setPending(value); setPurchaseBlocked(!!value); }
      catch { setPurchaseBlocked(true); }
      setBusy(false);
    }
  };

  if (USE_MOCK) return <DemoCredits returnTarget={returnTarget} />;

  return (
    <Screen>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingTop: 4 }}>
        <Text variant="display">{tr('Get credits')}</Text>
        <Pressable
          accessibilityRole="button" accessibilityLabel={tr('Close credit store')}
          onPress={() => returnTarget ? router.replace(returnTarget) : router.back()}
          style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: t.colors.surfaceRaisedStrong, alignItems: "center", justifyContent: "center" }}
        >
          <Text color={t.colors.textSecondary} style={{ fontSize: 16 }}>
            ✕
          </Text>
        </Pressable>
      </View>

      {!!returnTarget && <View style={{ gap: 8, marginTop: 16 }}>
        <Text>{tr('Your draft and saved generation request are retained. Check your balance, then return to retry generation.')}</Text>
        <Button label={tr('Return to your draft')} variant="secondary" disabled={busy} onPress={() => router.replace(returnTarget)} />
      </View>}

      <View
        style={{
          alignSelf: "flex-start",
          flexDirection: "row",
          alignItems: "center",
          gap: 7,
          paddingHorizontal: 12,
          paddingVertical: 7,
          backgroundColor: t.colors.accentTint,
          borderWidth: 1,
          borderColor: t.colors.accentBorder,
          borderRadius: t.radius.pill,
          marginTop: 10,
        }}
      >
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: t.colors.accent }} />
        <Text variant="label" family={t.fonts.displayMed} color={t.colors.accent} style={{ fontSize: 13 }}>
          {tr("Balance: {balance}", { balance: wallet.isError ? tr("unavailable") : wallet.data ? tr("{count} credits", { count: wallet.data.balance }) : tr("loading…") })}
        </Text>
      </View>

      {/* Packs */}
      <View style={{ gap: 12, marginTop: 22, flex: 1 }}>
        {packs.map(p => {
          const storeProduct = products.find(item => item.identifier === p.productId);
          return storeProduct ? <PackRow key={p.productId} pack={storeProduct} credits={p.credits} selected={p.productId === selected} onPress={() => { if (!busy) setSelected(p.productId); }} /> : null;
        })}
      </View>

      {/* CTA */}
      <View style={{ gap: 14, paddingBottom: 34 }}>
        {pending ? <View style={{ gap: 8 }}>
          <Text variant="bodySm">{tr("A checkout started on {date} is awaiting confirmation. Refresh or restore before buying again.", { date: new Date(pending.startedAt).toLocaleString(locale) })}</Text>
          <Button label={tr('Review unresolved purchase')} variant="ghost" disabled={busy} onPress={() => setReviewPending(true)} />
          {reviewPending ? <View style={{ gap: 8 }}>
            <Text variant="bodySm">{tr('Check your store purchase history and credit balance first. Continuing does not cancel or refund the earlier purchase. A new checkout may cause a second charge.')}</Text>
            <Button label={tr('I checked; allow another purchase')} variant="secondary" disabled={busy} onPress={async () => {
              try { await acknowledgePendingPurchase(); setPending(null); setPurchaseBlocked(false); setReviewPending(false); }
              catch { setMessage("Could not clear the saved checkout. Please try again later."); }
            }} />
          </View> : null}
        </View> : null}
        {message ? <Text variant="bodySm" accessibilityLiveRegion="polite">{tr(message)}</Text> : null}
        <Button label={tr('Refresh balance and purchases')} variant="ghost" onPress={() => { void refresh(); }} disabled={busy} />
        <Button
          label={product && pack ? tr("Buy {count} credits — {price}", { count: pack.credits, price: product.priceString }) : tr("Purchases unavailable")}
          onPress={buy}
          loading={busy}
          disabled={!product || purchaseBlocked}
          style={{ backgroundColor: t.isDark ? "#fff" : "#000" }}
        />
        <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "center", gap: 20 }}>
          <Pressable
            accessibilityRole="button" accessibilityLabel={tr('Restore purchases')}
            accessibilityState={{ disabled: busy || !IAP_CONFIGURED, busy }}
            style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 8 }}
            disabled={busy || !IAP_CONFIGURED}
            onPress={async () => {
              if (busy) return;
              setBusy(true);
              try {
                await restorePurchases();
                await refresh();
                setMessage("Restore check completed. Your server balance remains authoritative; consumed credits are not reissued.");
              } catch {
                setMessage("Restore could not be confirmed. Please check your balance and try again later.");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Text variant="bodySm" color={t.colors.textMuted}>{tr('Restore purchases')}</Text>
          </Pressable>
          <Pressable accessibilityRole="link" accessibilityLabel={tr('Terms')}
            onPress={() => void openPublicLink(TERMS_URL, "Terms")}
            style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 8 }}>
            <Text variant="bodySm" color={t.colors.textMuted}>{tr('Terms')}</Text>
          </Pressable>
        </View>
      </View>
      <View style={{ gap: 10, paddingBottom: 24 }}>
        <Text variant="subheading">{tr('Recent confirmed purchases')}</Text>
        <Text variant="bodySm">{tr('Latest 50 grants. A pending store purchase may take time to appear.')}</Text>
        {historyError ? <Text variant="bodySm" accessibilityRole="alert">{tr(historyError)}</Text> : history.length === 0 ? <Text variant="bodySm">{tr('No confirmed purchases yet.')}</Text> : null}
        {history.map(item => <View key={item.id}>
          <Text variant="bodySm">{tr("{count} credits", { count: item.credits })} · {tr(item.status === "reversed" ? "Refunded / reversed" : "Granted")}</Text>
          <Text variant="bodySm" color={t.colors.textMuted}>{new Date(item.createdAt).toLocaleString(locale)}</Text>
        </View>)}
      </View>
    </Screen>
  );
}

function PackRow({ pack, credits, selected, onPress }: { pack: PurchasesStoreProduct; credits: number; selected: boolean; onPress: () => void }) {
  const { tr } = useI18n();
  const t = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="radio" accessibilityState={{ selected }}
      style={{ padding: 18, borderRadius: t.radius.xl, backgroundColor: selected ? "#302844" : t.colors.surface,
        borderWidth: selected ? 1.5 : 1, borderColor: selected ? "#BCA3F5" : t.colors.border,
        flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <View style={{ flex: 1 }}>
        <Text variant="subheading" family={t.fonts.display}>{tr("{count} credits", { count: credits })}</Text>
        <Text variant="bodySm" color={t.colors.textSecondary} style={{ marginTop: 2 }}>{pack.description}</Text>
      </View>
      <Text variant="subheading" family={t.fonts.display}>{pack.priceString}</Text>
    </Pressable>
  );
}
