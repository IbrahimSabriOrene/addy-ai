import { useI18n, translate as tr } from "@/i18n";
import React, { useState } from "react";
import { View, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { TAB_BAR_HEIGHT } from "@/components/TabBar";
import { useTheme } from "@/theme/ThemeProvider";
import { useAccount, useWallet } from "@/api/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { clearTokens } from "@/lib/auth";
import { removeDeviceNotifications } from "@/lib/notifications";

export default function AccountScreen() {
  const { locale } = useI18n();
  const t = useTheme();
  const router = useRouter();
  const account = useAccount();
  const wallet = useWallet();
  const queries = useQueryClient();
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");

  async function signOut() {
    if (signingOut) return;
    setSigningOut(true); setSignOutError("");
    try {
      await removeDeviceNotifications().catch(() => {});
      await clearTokens();
      queries.clear();
      router.replace("/sign-in");
    } catch { setSignOutError(tr("Could not confirm sign-out. Please check your connection and try again.")); }
    finally { setSigningOut(false); }
  }

  return (
    <Screen bottomInset={TAB_BAR_HEIGHT}>
      <Text variant="display" style={{ paddingTop: 4 }}>
        {tr("Account")}</Text>

      {/* Profile */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 14,
          marginTop: 18,
          padding: 16,
          borderRadius: t.radius.xxl,
          backgroundColor: t.colors.surface,
          borderWidth: 1,
          borderColor: t.colors.borderSubtle,
        }}
      >
        <View style={{ width: 52, height: 52, borderRadius: 26, backgroundColor: t.colors.accent, alignItems: "center", justifyContent: "center" }}>
          <Text family={t.fonts.display} color={t.colors.accentInk} style={{ fontSize: 20 }}>
            {account.data?.initial ?? "?"}
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text variant="subheading" family={t.fonts.display}>
            {account.data?.name ?? "—"}
          </Text>
          <Text variant="bodySm" color={t.colors.textSecondary}>
            {account.data?.email ?? ""}
          </Text>
        </View>
      </View>

      {/* Credits */}
      <View
        style={{
          marginTop: 14,
          padding: 18,
          borderRadius: t.radius.xxl,
          backgroundColor: t.colors.accentTintStrong,
          borderWidth: 1,
          borderColor: t.colors.accentBorder,
        }}
      >
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12, justifyContent: "space-between", alignItems: "center" }}>
          <View>
            <Text variant="bodySm" color={t.colors.textSecondary}>
              {tr("Available credits")}</Text>
            <Text family={t.fonts.display} style={{ fontSize: 32, marginTop: 2 }}>
              {wallet.data?.balance ?? "—"}{" "}
              <Text family={t.fonts.displayReg} color={t.colors.textSecondary} style={{ fontSize: 16 }}>
                {tr("credits")}</Text>
            </Text>
          </View>
          <Pressable accessibilityRole="button" onPress={() => router.push("/paywall")} style={{ minHeight: 44, paddingHorizontal: 18, paddingVertical: 12, backgroundColor: t.colors.accent, borderRadius: t.radius.md + 2 }}>
            <Text variant="buttonSm" family={t.fonts.display} color={t.colors.accentInk} style={{ fontSize: 14 }}>
              {tr("Buy more")}</Text>
          </Pressable>
        </View>
        {!!wallet.data?.held && <Text variant="caption" color={t.colors.textSecondary} style={{ marginTop: 10 }}>
          {tr("{count} credits reserved for pending generations or review.", { count: wallet.data.held })}
        </Text>}
        {wallet.data?.pack && (
          <Text variant="caption" color={t.colors.textSecondary} style={{ marginTop: 10 }}>
            {tr("{pack} pack · {used} of {total} used", { pack: cap(wallet.data.pack), used: wallet.data.packUsed ?? 0, total: wallet.data.packSize ?? 0 })}
          </Text>
        )}
      </View>

      {/* Preferences */}
      <Pressable accessibilityRole="button" onPress={() => router.push("/language")} style={{ paddingVertical: 18, minHeight: 44 }}><Text variant="subheading">{tr("App language")}</Text></Pressable>
      <Pressable accessibilityRole="button" onPress={() => router.push("/campaign-progress")} style={{ paddingVertical: 18, minHeight: 44 }}><Text variant="subheading">{tr("Campaign progress")}</Text></Pressable>
      <Pressable accessibilityRole="button" onPress={() => router.push("/notifications")} style={{ paddingVertical: 18, minHeight: 44 }}><Text variant="subheading">{tr("Notifications & reminders")}</Text></Pressable>
      <Pressable accessibilityRole="button" onPress={() => router.push("/brand")} style={{ paddingVertical: 18, minHeight: 44 }}>
        <Text variant="subheading">{tr("Brand profile")}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={() => router.push("/products")} style={{ paddingVertical: 18 }}>
        <Text variant="subheading">{tr("My Products")}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={() => router.push("/ai-sharing")} style={{ paddingVertical: 18 }}>
        <Text variant="subheading">{tr("AI sharing")}</Text>
      </Pressable>
      <View style={{ height: 14 }} />
      <Group>
        <Row label={tr("Age eligibility")} border onPress={() => router.push("/age-check")} />
        <Row label={tr("Privacy & legal")} border onPress={() => router.push("/privacy-legal")} />
        <Row label={tr("Help & support")} trailing={<Text color={t.colors.textMuted} style={{ fontSize: 18 }}>›</Text>} border onPress={() => router.push("/support")} />
        <Pressable accessibilityRole="button" onPress={() => router.push("/delete-account")} style={{ paddingHorizontal: 16, paddingVertical: 15 }}>
          <Text variant="bodyStrong" color={t.colors.danger}>{tr("Delete account")}</Text>
        </Pressable>
        <Row label={signingOut ? tr("Signing out…") : tr("Sign out")} busy={signingOut} labelColor={t.colors.danger} onPress={() => void signOut()} />
      </Group>
      {!!signOutError && <Text accessibilityRole="alert">{tr(signOutError)}</Text>}
    </Screen>
  );
}

function Group({ children }: { children: React.ReactNode }) {
  const t = useTheme();
  return (
    <View style={{ borderRadius: t.radius.xl, overflow: "hidden", backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.borderSubtle }}>
      {children}
    </View>
  );
}

function Row({
  label,
  trailing,
  border,
  labelColor,
  onPress,
  busy = false,
}: {
  label: string;
  trailing?: React.ReactNode;
  border?: boolean;
  labelColor?: string;
  onPress?: () => void;
  busy?: boolean;
}) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: busy, busy }}
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: 16,
        paddingVertical: 15,
        borderBottomWidth: border ? 1 : 0,
        borderBottomColor: t.colors.borderSubtle,
      }}
    >
      <Text variant="bodyStrong" color={labelColor ?? t.colors.text}>
        {label}
      </Text>
      {trailing}
    </Pressable>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
