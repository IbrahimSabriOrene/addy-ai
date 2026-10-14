import { useI18n, translate } from "@/i18n";
import React from "react";
import { View, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { Check, Camera, ChevronBack } from "@/components/Icons";
import { useTheme } from "@/theme/ThemeProvider";

const TIPS = ["Good lighting, plain background", "One product, filling the frame"];

export default function ReshootScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();

  return (
    <Screen bottomInset={24}>
      {/* Back button */}
      <Pressable
        accessibilityRole="button" accessibilityLabel={translate("Go back")}
        onPress={() => router.back()}
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          backgroundColor: t.colors.surfaceRaisedStrong,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ChevronBack size={18} color={t.colors.text} />
      </Pressable>

      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 26 }}>


        <View style={{ alignItems: "center" }}>
          <Text variant="display" center style={{ fontSize: 25, letterSpacing: -0.4 }}>
            {translate("Let's try that photo again")}</Text>
          <Text variant="body" center color={t.colors.textSecondary} style={{ marginTop: 12, maxWidth: 290, fontSize: 14.5, lineHeight: 22.5 }}>
            {translate("Choose a clear, well-lit photo of one product. Check the previous job and credit status in your library. A new generation shows its price before you confirm.")}</Text>
        </View>

        <View style={{ width: "100%", gap: 10 }}>
          {TIPS.map((tip) => (
            <View
              key={translate(tip)}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 10,
                paddingHorizontal: 14,
                paddingVertical: 12,
                backgroundColor: t.colors.surfaceRaised,
                borderRadius: t.radius.md + 2,
              }}
            >
              <View style={{ width: 22, height: 22, borderRadius: 7, backgroundColor: t.colors.accentTintStrong, alignItems: "center", justifyContent: "center" }}>
                <Check size={12} color={t.colors.accent} strokeWidth={3} />
              </View>
              <Text variant="bodySm" color={t.colors.textSecondary} style={{ fontSize: 13 }}>
                {translate(tip)}
              </Text>
            </View>
          ))}
        </View>
      </View>

      <Button
        label={translate("Choose a style for a new photo")}
        icon={<Camera size={18} color={t.colors.accentInk} />}
        onPress={() => router.replace("/create/browse")}
        style={{ marginBottom: 34 }}
      />
      <Button label={translate("Check previous job in library")} variant="secondary" onPress={() => router.replace("/library")} />
    </Screen>
  );
}
