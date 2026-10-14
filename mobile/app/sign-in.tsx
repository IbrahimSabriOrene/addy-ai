import { useI18n, translate } from "@/i18n";
import { SignInShowcase } from "@/components/SignInShowcase";
import React, { useState } from "react";
import * as AppleAuthentication from "expo-apple-authentication";
import { View, Pressable, Image, useWindowDimensions } from "react-native";
import { openPublicLink, TERMS_URL, PRIVACY_URL } from "@/lib/publicLinks";
import { useLocalSearchParams, useRouter } from "expo-router";
import { req, USE_MOCK } from "@/api/client";
import { draftReturn } from "@/lib/draftReturn";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { Glow } from "@/components/Glow";
import { Apple } from "@/components/Icons";
import { useTheme } from "@/theme/ThemeProvider";
import { markOnboarded } from "@/lib/onboarding";
import { supabase } from "@/lib/supabase";

// WI-001: set false to restore the previous background.
const SHOW_SIGN_IN_SHOWCASE = true;

export default function SignInScreen() {
  useI18n();
  const t = useTheme();
  const { height } = useWindowDimensions();
  const router = useRouter();
  const { returnTo } = useLocalSearchParams<{ returnTo?: string }>();
  const returnTarget = draftReturn(returnTo);
  const [error, setError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  const [about, setAbout] = useState(false);

  const enter = async () => {
    if (__DEV__ && USE_MOCK) { await markOnboarded(); router.replace(returnTarget ?? "/home"); return; }
    if (!supabase) {
      setError("Sign-in is not configured yet.");
      return;
    }
    setSigningIn(true);
    setError(null);
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [AppleAuthentication.AppleAuthenticationScope.FULL_NAME, AppleAuthentication.AppleAuthenticationScope.EMAIL],
      });
      if (!credential.identityToken) throw new Error("Apple did not return an identity token.");
      const { data, error: authError } = await supabase.auth.signInWithIdToken({
        provider: "apple", token: credential.identityToken,
      });
      if (authError || !data.session) throw authError ?? new Error("Sign-in did not create a session.");
      await markOnboarded();
      const eligibility = await req<{ confirmed: boolean }>("/v1/account/eligibility").catch(() => ({ confirmed: false }));
      router.replace(eligibility.confirmed ? (returnTarget ?? "/home") : { pathname: "/age-check", params: typeof returnTo === "string" ? { returnTo } : {} });
    } catch (cause) {
      if ((cause as { code?: string }).code !== "ERR_REQUEST_CANCELED") setError("Sign-in failed. Please try again.");
    } finally {
      setSigningIn(false);
    }
  };



  return (
    <Screen padded={false} backgroundLayer={SHOW_SIGN_IN_SHOWCASE ? <SignInShowcase /> : <Glow cy="8%" ry="80%" fadeEnd={0.5} />}>
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 30, paddingTop: SHOW_SIGN_IN_SHOWCASE ? Math.max(24, Math.min(140, (height - 560) * 0.5)) : 0, gap: 26 }}>
        <Image source={require("../assets/brand/addy-icon.png")} accessibilityLabel={translate("Addy AI logo")} resizeMode="contain" style={{ width: 112, height: 112 }} />

        {/* Title + subtitle */}
        <View style={{ alignItems: "center" }}>
          <Text variant="display" style={{ fontSize: 28, letterSpacing: -0.5 }}>
            {translate("Addy AI")}</Text>
          <Text
            variant="body"
            center
            color={t.colors.textSecondary}
            style={{ marginTop: 10, maxWidth: 270, fontSize: 15, lineHeight: 22 }}
          >
            {translate("Create a new look for your product. For adults 18+ using Addy AI for professional or business purposes.")}</Text>
        </View>

        <View style={{ alignItems: "center", maxWidth: 300 }}>
          <Pressable accessibilityRole="button" accessibilityState={{ expanded: about }} onPress={() => setAbout(!about)} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 12 }}>
            <Text color={t.colors.textSecondary}>{translate("About Addy AI")} {about ? "−" : "+"}</Text>
          </Pressable>
          {about && <>
          <Text variant="bodySm" center color={t.colors.textSecondary}>
            {translate("Made for independent online sellers")}</Text>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", flexWrap: "wrap" }}>
            <Text variant="bodySm" color={t.colors.textSecondary}>{translate("Etsy sellers &")}</Text>
            <Pressable accessibilityRole="link" accessibilityLabel={translate("Shopify homepage")} onPress={() => void openPublicLink("https://www.shopify.com", "Shopify")} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 4 }}>
              <Text variant="bodySm" color={t.colors.textSecondary} style={{ textDecorationLine: "underline" }}>{translate("Shopify merchants")}</Text>
            </Pressable>
          </View>
          <Text variant="caption" center color={t.colors.textMuted}>
            {translate("Independent app. Not affiliated with or endorsed by Etsy or Shopify. No store connection.")}</Text>
          </>}
        </View>
      </View>

      {/* Bottom section */}
      <View style={{ paddingHorizontal: 30, paddingBottom: 40, gap: 14 }}>
        <Pressable
          accessibilityRole="button" accessibilityLabel={__DEV__ && USE_MOCK ? translate("Enter demo") : translate("Sign in with Apple")}
          onPress={enter}
          disabled={signingIn}
          style={{
            height: 56,
            borderRadius: 16,
            backgroundColor: t.isDark ? "#fff" : "#000",
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
            opacity: signingIn ? 0.6 : 1,
          }}
        >
          <Apple size={19} color={t.isDark ? "#000" : "#fff"} />
          <Text variant="button" color={t.isDark ? "#000" : "#fff"}>
            {__DEV__ && USE_MOCK ? translate("Enter demo") : translate("Sign in with Apple")}
          </Text>
        </Pressable>

        {error && <Text variant="bodySm" center color="#f87171">{translate(error)}</Text>}

        <Text
          variant="bodySm"
          center
          color={t.colors.textMuted}
          style={{ fontSize: 12, lineHeight: 18, maxWidth: 290, alignSelf: "center" }}
        >
          {__DEV__ && USE_MOCK ? translate("Demo preview. No real account, AI processing or payment. You can enter again after signing out.") : translate("Sign in to access your saved products, creations and credits. No password to remember.")}
        </Text>

        <View style={{ alignItems: "center" }}>
          <Pressable accessibilityRole="button" onPress={() => router.push("/language")} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 12 }}><Text>{translate("App language")}</Text></Pressable>
          <Text variant="caption" center color={t.colors.textMuted}>
            {__DEV__ && USE_MOCK ? translate("Preview our draft documents") : translate("By continuing, you agree to our Terms. Read our Privacy notice.")}
          </Text>
          <View style={{ flexDirection: "row", justifyContent: "center", gap: 16 }}>
            <Pressable accessibilityRole="link" accessibilityLabel={translate("Terms")} onPress={() => void openPublicLink(TERMS_URL, "Terms")} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 8 }}>
              <Text variant="caption" color={t.colors.textSecondary} style={{ textDecorationLine: "underline" }}>{translate("Terms")}</Text>
            </Pressable>
            <Pressable accessibilityRole="link" accessibilityLabel={translate("Privacy notice")} onPress={() => void openPublicLink(PRIVACY_URL, "Privacy notice")} style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: 8 }}>
              <Text variant="caption" color={t.colors.textSecondary} style={{ textDecorationLine: "underline" }}>{translate("Privacy notice")}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Screen>
  );
}
