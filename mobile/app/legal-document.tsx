import { useI18n, translate as tr } from "@/i18n";
import React from "react";
import { View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { useTheme } from "@/theme/ThemeProvider";
import drafts from "@/lib/legalDrafts.json";

export default function LegalDocumentScreen() {
  const { locale } = useI18n();
  const { document } = useLocalSearchParams<{ document?: string }>();
  const t = useTheme();
  const draft = __DEV__ && (document === "terms" || document === "privacy") ? drafts[document] : null;
  return <Screen scroll={false}>
    <TopBar title={tr(draft?.title ?? "Legal document")} fallbackHref="/sign-in" />
    <Screen padded={false} bottomInset={24}>
      {!draft ? <Text>{tr("This document is not available.")}</Text> : <View style={{ gap: 18 }}>
        <View style={{ padding: 14, borderRadius: 14, backgroundColor: t.colors.surface }}>
          {locale !== "en" && <Text>{tr("This draft is currently available in English.")}</Text>}
          <Text variant="subheading">{tr("Draft · Not final")}</Text>
          <Text variant="bodySm" color={t.colors.textSecondary}>{tr("For review only. Operator details and legal review are incomplete.")}</Text>
        </View>
        {draft.body.split(/\r?\n\s*\r?\n/).slice(1).map((paragraph, index) => {
          const heading = paragraph.startsWith("## ");
          return <Text key={index} selectable accessibilityRole={heading ? "header" : undefined} variant={heading ? "subheading" : "body"}>
            {paragraph.replace(/^## /, "").replace(/\r?\n(?!- )\s*/g, " ").trim()}
          </Text>;
        })}
      </View>}
    </Screen>
  </Screen>;
}
