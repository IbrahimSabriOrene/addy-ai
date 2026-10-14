import { useI18n, translate as tr } from "@/i18n";
import React, { useState } from "react";
import { Pressable, View } from "react-native";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { SUPPORT_URL, openPublicLink } from "@/lib/publicLinks";
import { useTheme } from "@/theme/ThemeProvider";

const answers = [
  ["How do I make an ad?", "Open Create, choose a style, then add your product photo. Review the price before generating. In this demo, you can preview bundled samples for free."],
  ["How do I share my video?", "Open a creation and tap Share to apps. Choose an installed app, then review and publish there. You can also download the video and copy its caption."],
  ["Where are my products?", "Open My Products from Home or Account. Tap a product to see its creations. Demo products are kept only until the app reloads."],
  ["Why is a preview not moving?", "Only the active gallery preview plays. Reduced-motion settings can turn off autoplay. Open a style to use its playback controls. If media is still loading, check your connection."],
  ["Are demo credits real purchases?", "No. Demo credits are free preview controls. Adding or restoring them does not charge you or restore a store purchase."],
];
export default function SupportScreen() {
  const { locale } = useI18n();
  const t = useTheme();
  const [open, setOpen] = useState<number | null>(null);
  return <Screen bottomInset={24}>
    <TopBar title={tr("Help & support")} fallbackHref="/account" />
    <View style={{ gap: 12, marginTop: 24 }}>
      {answers.map(([question, answer], index) => <View key={question} style={{ padding: 16, borderRadius: 16, backgroundColor: t.colors.surface }}>
        <Pressable accessibilityRole="button" accessibilityState={{ expanded: open === index }} onPress={() => setOpen(open === index ? null : index)} style={{ minHeight: 44, justifyContent: "center" }}><Text variant="cardTitle">{tr(question)}</Text></Pressable>
        {open === index && <Text style={{ marginTop: 8 }} color={t.colors.textSecondary}>{tr(answer)}</Text>}
      </View>)}
      {SUPPORT_URL ? <Button label={tr("Contact support")} onPress={() => void openPublicLink(SUPPORT_URL, "Support", true)} />
        : <Text variant="caption" color={t.colors.textMuted}>{tr("Direct support will be available at launch.")}</Text>}
    </View>
  </Screen>;
}
