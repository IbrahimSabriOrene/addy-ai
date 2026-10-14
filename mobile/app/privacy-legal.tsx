import { useI18n, translate as tr } from "@/i18n";
import React from "react";
import { View } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { openPublicLink, PRIVACY_URL, TERMS_URL, SUPPORT_URL } from "@/lib/publicLinks";

export default function PrivacyLegalScreen() {
  const { locale } = useI18n();
  const router = useRouter();
  return <Screen bottomInset={24}>
    <TopBar title={tr("Privacy & legal")} fallbackHref="/account" />
    <View style={{ gap: 16, paddingVertical: 20 }}>
      <Text>{tr("Read how your information is handled and the terms for using Addy AI.")}</Text>
      <Button label={tr("Privacy notice")} variant="secondary" onPress={() => void openPublicLink(PRIVACY_URL, "Privacy notice")} />
      <Button label={tr("Terms of use")} variant="secondary" onPress={() => void openPublicLink(TERMS_URL, "Terms")} />
      {(!PRIVACY_URL || !TERMS_URL) && <Text accessibilityRole="alert">{tr("Draft documents are available for review. Published legal documents are not configured.")}</Text>}
      <Text variant="subheading">{tr("Your information and choices")}</Text>
      <Text>{tr("You can ask about access to your personal information, a copy or correction, deletion, or restrictions on its use. Available rights and exceptions depend on the law that applies to you.")}</Text>
      <Text>{tr("Use the support contact to make a privacy request. Include the account email and what you need; do not send your password, payment card details or identity documents in the initial message.")}</Text>
      <Button label={tr("Contact support about privacy")} variant="secondary" onPress={() => void openPublicLink(SUPPORT_URL, "Privacy support", true)} />
      {!SUPPORT_URL && <Text accessibilityRole="alert">{tr("A privacy support contact has not been configured for this preview.")}</Text>}
      <Button label={tr("Manage AI-sharing permission")} variant="secondary" onPress={() => router.push("/ai-sharing")} />
      <Text>{tr("Withdrawing AI-sharing permission stops new transfers; it cannot undo requests already submitted. Photo-library permission is separate.")}</Text>
      <Button label={tr("Delete my account")} variant="ghost" onPress={() => router.push("/delete-account")} />
      <Text>{tr("Review the deletion screen before confirming. Removing a saved product is different from deleting your account and its associated data.")}</Text>
    </View>
  </Screen>;
}
