import { translate as tr, useI18n, Locale } from "@/i18n";
import React, { useState } from "react";
import { View } from "react-native";
import { Button } from "./Button";
import { Text } from "./Text";
import { CampaignLanguage } from "./CampaignLanguage";
import { ProductPreview } from "./ProductPreview";

export type Objective = "new_product" | "weekend" | "seasonal" | "clearance";
type Brief = { campaignLanguage?: Locale; objective?: Objective; offer: string; caption: string; cta: string; color: string; contact?: string };
const goals: [Objective, string, string][] = [
  ["new_product", "Introduce a product", "Explore the collection"],
  ["weekend", "Weekend campaign", "Plan your visit"],
  ["seasonal", "Seasonal campaign", "Find your favourite"],
  ["clearance", "Stock clearance", "See available products"],
];

export function CampaignPlanner({ brief, assetKey, disabled, onChange }: {
  brief: Brief; assetKey: string; disabled: boolean; onChange: (patch: Partial<Brief>) => void;
}) {
  useI18n();
  const [open, setOpen] = useState(false), [preview, setPreview] = useState(false);
  const campaignLanguage = brief.campaignLanguage ?? "en";
  const ready = [!!assetKey, !!brief.offer.trim(), !!brief.cta.trim()].filter(Boolean).length;
  return <View style={{ gap: 8 }}>
    <CampaignLanguage value={campaignLanguage} disabled={disabled} onChange={campaignLanguage => onChange({ campaignLanguage })} />
    <Button label={open ? tr("Close campaign planning") : tr("Campaign purpose & free preview")} variant="secondary" onPress={() => setOpen(!open)} />
    {open && <>
      <Text>{tr("{v0}/3 ready: product, offer, call to action. Your choices are saved as you go.", { v0: ready })}</Text>
      <Text>{tr("Choose a purpose. Suggested wording is editable; no discounts or deadlines are invented.")}</Text>
      {goals.map(([goal, label, cta]) => <Button key={goal} label={tr(label)} variant={brief.objective === goal ? "selected" : "secondary"} disabled={disabled}
        onPress={() => onChange({ objective: goal, ...(!brief.cta.trim() ? { cta: tr(cta, {}, campaignLanguage) } : {}) })} />)}
      <Button label={preview ? tr("Close free draft preview") : tr("Preview draft · no credits")} variant="secondary" onPress={() => setPreview(!preview)} />
      {preview && <>
        <Text>{tr("Draft composition, not a generated video or exact export. Saved campaign layouts provide the final text rendering.")}</Text>
        <View style={{ backgroundColor: /^#[0-9a-fA-F]{6}$/.test(brief.color) ? brief.color : "#FFFFFF", padding: 16, gap: 12, borderRadius: 12 }}>
          <View style={{ backgroundColor: "#fff", padding: 8 }}><Text color="#111">{brief.offer || tr("Your offer")}</Text></View>
          <ProductPreview assetKey={assetKey} />
          <View style={{ backgroundColor: "#fff", padding: 8 }}><Text color="#111">{brief.cta || tr("Your call to action")}</Text><Text color="#111">{brief.contact}</Text></View>
        </View>
        <Text>{brief.caption || tr("Add your caption below.")}</Text>
      </>}
      <Text>{tr("Three message options · uses your exact offer. Applying one changes the draft only.")}</Text>
      {[
        ["Use product focus", "Explore the collection"],
        ["Use conversation focus", "Message us for details"],
        ["Use purchase focus", "Shop this product"],
      ].map(([label, cta]) => <Button key={label} label={tr(label)} variant="secondary" disabled={disabled}
        onPress={() => { const suggestion = tr(cta, {}, campaignLanguage); onChange({ cta: suggestion, caption: [brief.offer, suggestion].filter(Boolean).join("\n") }); }} />)}
      <Text>{tr("Save an option, then update a delivered video's on-screen text for free. Speech stays unchanged; new video generation has a separate price.")}</Text>
    </>}
  </View>;
}
