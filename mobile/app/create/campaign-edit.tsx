import { translate as tr, useI18n } from "@/i18n";
import React from "react";
import { useLocalSearchParams } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { CampaignDetails } from "@/components/ProductCampaigns";

export default function CampaignEditScreen() {
  useI18n();
  const { campaign } = useLocalSearchParams<{ campaign: string }>();
  return <Screen bottomInset={24}>
    <TopBar title={tr("Edit campaign")} />
    <Text>{tr("Edit the latest campaign details. Earlier generated packs stay in campaign history. Saving text does not spend credits.")}</Text>
    {typeof campaign === "string" && campaign
      ? <CampaignDetails key={campaign} id={campaign} />
      : <Text>{tr("Open a campaign result to edit its details.")}</Text>}
  </Screen>;
}
