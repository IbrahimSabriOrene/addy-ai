import React, { useState } from "react";
import { View } from "react-native";
import { Locale, useI18n } from "@/i18n";
import { Button } from "./Button";
import { Text } from "./Text";

const languages: [Locale, string][] = [["en", "English"], ["tr", "Türkçe"], ["pt-BR", "Português (Brasil)"], ["es", "Español"]];

export function CampaignLanguage({ value = "en", disabled, onChange }: { value?: Locale; disabled: boolean; onChange: (value: Locale) => void }) {
  const { tr } = useI18n();
  const [open, setOpen] = useState(false);
  return <View style={{ gap: 8 }}>
    <Button label={tr("Campaign language: {language}", { language: languages.find(([code]) => code === value)?.[1] ?? "English" })}
      variant="secondary" disabled={disabled} onPress={() => setOpen(!open)} />
    {open && <>
      <Text>{tr("Choose the language for campaign suggestions. Existing offers, prices and captions stay exactly as written. This does not guarantee the language of generated speech.")}</Text>
      {languages.map(([code, label]) => <Button key={code} label={label} variant={value === code ? "selected" : "secondary"}
        disabled={disabled} onPress={() => { onChange(code); setOpen(false); }} />)}
    </>}
  </View>;
}
