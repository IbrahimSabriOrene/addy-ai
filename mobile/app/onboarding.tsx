import { useI18n, translate } from "@/i18n";
import React, { useRef, useState } from "react";
import { View, Pressable, ScrollView, Dimensions, useWindowDimensions, LayoutChangeEvent, NativeSyntheticEvent, NativeScrollEvent } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { MediaPlaceholder } from "@/components/MediaPlaceholder";
import { Glow } from "@/components/Glow";
import { useTheme } from "@/theme/ThemeProvider";

const SLIDES = [
  {
    badge: "Made for small shops",
    title: "A new look for\nyour product",
    body: "Start with a clear product photo and review each result before sharing.",
    chip: "9:16",
  },
  {
    badge: "Made to share",
    title: "Choose where\nto share",
    body: "Download your results and review them before sharing on your chosen platform.",
    chip: "Download",
  },
  {
    badge: "Review your choices",
    title: "Choose your\ncreative direction",
    body: "Choose a style, add optional instructions and review the credit cost before generating.",
    chip: "You choose",
  },
];

export default function OnboardingScreen() {
  useI18n();
  const t = useTheme();
  const { height, fontScale } = useWindowDimensions();
  const mediaHeight = Math.min(300, Math.max(96, height * 0.28 / Math.max(1, fontScale)));
  const router = useRouter();
  const [width, setWidth] = useState(Dimensions.get("window").width);
  const [page, setPage] = useState(0);
  const scroller = useRef<ScrollView>(null);
  const onPagerLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);

  const enter = () => {
    router.replace("/sign-in");
  };

  const next = () => {
    if (page < SLIDES.length - 1) scroller.current?.scrollTo({ x: (page + 1) * width, animated: true });
    else enter();
  };

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    setPage(Math.round(e.nativeEvent.contentOffset.x / width));
  };

  return (
    <Screen scroll={false} padded={false} backgroundLayer={<Glow />}>
      {/* Top row: badge + skip */}
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: t.space.screenX, paddingTop: 8 }}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            paddingHorizontal: 11,
            paddingVertical: 5,
            backgroundColor: "rgba(232,168,90,0.14)",
            borderWidth: 1,
            borderColor: "rgba(232,168,90,0.3)",
            borderRadius: t.radius.pill,
          }}
        >
          <Text style={{ fontSize: 12 }}>🧵</Text>
          <Text variant="label" family={t.fonts.bodySemi} color="#d4a05a" style={{ fontSize: 11.5 }}>
            {translate(SLIDES[page].badge)}
          </Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={translate("Skip onboarding")} onPress={enter} style={{ minHeight: 44, minWidth: 44, justifyContent: "center" }}>
          <Text variant="bodyStrong" color={t.colors.textMuted}>
            {translate("Skip")}</Text>
        </Pressable>
      </View>

      <ScrollView
        ref={scroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        onLayout={onPagerLayout}
        style={{ flex: 1 }}
      >
        {SLIDES.map((s, i) => (
          <ScrollView key={i} style={{ width }} showsVerticalScrollIndicator={false} contentContainerStyle={{ flexGrow: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 24, paddingVertical: 16, gap: 20 }}>
            <MediaPlaceholder source={[require("../public/previews/skincare_glow.png"), require("../public/previews/bakery_morning.png"), require("../public/previews/jewelry_detail.png")][i]} label={translate("Example product ad")} tone="teal" style={{ width: mediaHeight * 23 / 30, height: mediaHeight, borderRadius: t.radius.card }}>
              <View style={{ position: "absolute", bottom: 14, left: 14, flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 9, paddingVertical: 5, backgroundColor: "rgba(0,0,0,0.6)", borderRadius: t.radius.pill }}>
                <View style={{ width: 11, height: 15, borderRadius: 3, backgroundColor: t.platform.tiktok }} />
                <Text variant="label" family={t.fonts.displayMed} color="#fff" style={{ fontSize: 10 }}>
                  {translate(s.chip)}
                </Text>
              </View>

            </MediaPlaceholder>

            <View style={{ alignItems: "center" }}>
              <Text variant="displayLg" center>
                {translate(s.title)}
              </Text>
              <Text variant="body" center color={t.colors.textSecondary} style={{ marginTop: 14, maxWidth: 280, fontSize: 15, lineHeight: 22 }}>
                {translate(s.body)}
              </Text>
            </View>

          </ScrollView>
        ))}
      </ScrollView>

      {/* Dots */}
      <View style={{ flexDirection: "row", justifyContent: "center", gap: 7, marginBottom: 22 }}>
        {SLIDES.map((_, i) => (
          <View
            key={i}
            style={{
              width: i === page ? 22 : 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: i === page ? t.colors.accent : t.colors.textFaint,
            }}
          />
        ))}
      </View>

      <View style={{ paddingHorizontal: t.space.screenX, paddingBottom: 34 }}>
        <Button label={page === SLIDES.length - 1 ? translate("Upload your first product") : translate("Continue")} onPress={next} />
      </View>
    </Screen>
  );
}
