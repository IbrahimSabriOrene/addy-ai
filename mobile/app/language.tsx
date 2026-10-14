import React from "react";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { LanguagePicker } from "@/components/LanguagePicker";
import { useI18n } from "@/i18n";

export default function LanguageScreen() {
  const { tr } = useI18n();
  return <Screen contentStyle={{ gap: 20 }}><TopBar title={tr("App language")} /><LanguagePicker />
    <Text>{tr("Your campaign language is selected separately. Your product names, offers and saved text stay unchanged.")}</Text>
  </Screen>;
}
