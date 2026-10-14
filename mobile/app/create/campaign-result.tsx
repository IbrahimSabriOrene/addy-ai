import { translate as tr, useI18n } from "@/i18n";
import React from "react";
import { useLocalSearchParams } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { CampaignResults } from "@/components/CampaignResults";
import { Text } from "@/components/Text";

export default function CampaignResultScreen() {
  useI18n();
  const { campaign, version } = useLocalSearchParams<{ campaign: string; version: string }>();
  const number = Number(version);
  return <Screen bottomInset={24}>
    <TopBar title={tr("Your campaign")} />
    {campaign && Number.isSafeInteger(number) && number > 0
      ? <CampaignResults key={`${campaign}-${number}`} campaignId={campaign} version={number} />
      : <Text>{tr("Open a saved campaign to view its results.")}</Text>}
  </Screen>;
}
