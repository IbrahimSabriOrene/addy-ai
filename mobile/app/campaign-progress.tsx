import { useI18n, translate as tr } from "@/i18n";
import React, { useEffect, useState } from "react";
import { View } from "react-native";
import { router } from "expo-router";
import { req, USE_MOCK } from "@/api/client";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";

export default function CampaignProgressScreen() {
  const { locale } = useI18n();
  const [stats, setStats] = useState<{ products: number; campaigns: number; delivered: number; publishedSelfReported: number } | null>(null);
  const [error, setError] = useState("");
  async function load() {
    if (USE_MOCK) { setError(tr("Connect your account to see real campaign progress.")); return; }
    try { setStats(await req("/v1/account/engagement/stats")); setError(""); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  useEffect(() => { void load(); }, []);
  return <Screen bottomInset={24}><TopBar title={tr("Campaign progress")} /><View style={{ gap: 12, marginTop: 20 }}>
    {stats && <>
      <Text>{tr("{products} saved products · {campaigns} campaigns · {delivered} delivered creations", stats)}</Text>
      <Text>{tr("{count} campaigns marked published by you.", { count: stats.publishedSelfReported })}</Text>
      <Text>{!stats.products ? tr("Start with a product you want to promote.") : !stats.campaigns ? tr("Your product is ready for its first campaign.") : !stats.publishedSelfReported ? tr("Review a campaign and share it when you are ready.") : tr("Reuse a campaign you liked with your next offer.")}</Text>
      <Button label={stats.products ? tr("Continue with My Products") : tr("Choose a campaign example")} onPress={() => router.push(stats.products ? "/products" : "/create/browse")} />
    </>}
    <Button label={tr("Manage reminders")} variant="secondary" onPress={() => router.push("/notifications")} />
    <Button label={tr("Refresh progress")} variant="ghost" onPress={() => void load()} />
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
  </View></Screen>;
}
