import { TimeZoneField } from "@/components/TimeZoneField";
import { useI18n, translate as tr } from "@/i18n";
import React, { useEffect, useState } from "react";
import { Switch, View } from "react-native";
import { router } from "expo-router";
import { req, USE_MOCK } from "@/api/client";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { enableDeviceNotifications, removeDeviceNotifications } from "@/lib/notifications";
import { useTheme } from "@/theme/ThemeProvider";

type Prefs = { completion: boolean; weekly: boolean; analytics: boolean; weekday: number; hour: number; timezone: string; locale?: string };
type Notice = { id: string; kind: string; read: boolean };
export default function NotificationsScreen() {
  const { locale } = useI18n();
  const t = useTheme(), [prefs, setPrefs] = useState<Prefs | null>(null), [version, setVersion] = useState(0);
  const [items, setItems] = useState<Notice[]>([]), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  async function load() {
    if (USE_MOCK) { setMessage(tr("Sign in to a connected account to manage reminders and your inbox.")); return; }
    setBusy(true); setMessage("");
    try {
      const [saved, inbox] = await Promise.all([req<{ preferences: Prefs; version: number }>("/v1/account/engagement"), req<{ items: Notice[] }>("/v1/account/notifications")]);
      setPrefs(saved.preferences); setVersion(saved.version); setItems(inbox.items);
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  async function save() {
    if (!prefs || busy) return;
    setBusy(true); setMessage("");
    try {
      const saved = await req<{ version: number }>("/v1/account/engagement", { method: "PUT", body: JSON.stringify({ ...prefs, locale, expectedVersion: version }) });
      setVersion(saved.version);
      if (!prefs.completion && !prefs.weekly) await removeDeviceNotifications();
      setMessage(tr("Preferences saved. Device push is optional and can be enabled below."));
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  return <Screen bottomInset={24}><TopBar title={tr("Notifications & preferences")} />
    <View style={{ gap: 14, marginTop: 16 }}>
      {prefs && <>
        {([['completion', tr("Creation completed")], ['weekly', tr("Weekly campaign reminder")], ['analytics', tr("Share minimal usage statistics")]] as const).map(([key, label]) => <View key={key} style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 }}>
          <Text style={{ flex: 1 }}>{label}</Text><Switch accessibilityLabel={label} value={prefs[key]} disabled={busy} onValueChange={value => setPrefs({ ...prefs, [key]: value })} />
        </View>)}
        <Text>{tr("All options are optional. No purchase reminders. Push summaries are limited to one per 24 hours, between 09:00 and 20:00 in your selected time zone.")}</Text>
        <Text>{tr("Usage statistics contain daily screen/export events, not your photos or text. Turning them off deletes those events.")}</Text>
        <TimeZoneField value={prefs.timezone} disabled={busy} onChange={timezone => setPrefs({ ...prefs, timezone })} />
        {prefs.weekly && <>
          <Text>{tr("When would you like to plan your next campaign?")}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {[tr("Monday"),tr("Tuesday"),tr("Wednesday"),tr("Thursday"),tr("Friday"),tr("Saturday"),tr("Sunday")].map((day, weekday) => <Button key={day} label={day} style={{ flexGrow: 1, flexBasis: "40%" }} variant={prefs.weekday === weekday ? "selected" : "secondary"} onPress={() => setPrefs({ ...prefs, weekday })} disabled={busy} />)}
          </View>
          <Text>{tr("Reminder hour")} · {String(prefs.hour).padStart(2, "0")}:00</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Button label={`${tr("Reminder hour")} −1`} variant="secondary" style={{ flex: 1 }} disabled={busy || prefs.hour <= 9} onPress={() => setPrefs({ ...prefs, hour: Math.max(9, prefs.hour - 1) })} />
            <Button label={`${tr("Reminder hour")} +1`} variant="secondary" style={{ flex: 1 }} disabled={busy || prefs.hour >= 19} onPress={() => setPrefs({ ...prefs, hour: Math.min(19, prefs.hour + 1) })} />
          </View>
        </>}
        <Text>{tr("Notification language after saving: {language}", { language: { en: "English", tr: "Türkçe", "pt-BR": "Português (Brasil)", es: "Español" }[locale] })}</Text>
        <Button label={tr("Save preferences")} disabled={busy} onPress={() => void save()} />
        <Text>{tr("Device notifications use Expo and Apple/Google. They receive a device token and a generic notification message. Product photos and offers are not included.")}</Text>
        <Button label={tr("Enable device push after saving")} variant="secondary" disabled={busy || (!prefs.completion && !prefs.weekly)} onPress={() => { setBusy(true); void enableDeviceNotifications().then(() => setMessage(tr("This device is registered for your chosen notifications."))).catch(e => setMessage(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false)); }} />
      </>}
      <Text>{tr("Inbox")}</Text>
      {!items.length && <Text>{tr("No updates yet.")}</Text>}
      {items.map(item => <Button key={item.id} label={item.read ? tr(item.kind === "completion" ? "Review your creation" : "Plan your next campaign") : tr("New · {message}", { message: tr(item.kind === "completion" ? "Review your creation" : "Plan your next campaign") })} variant="secondary" onPress={() => {
        void req(`/v1/account/notifications/${item.id}/read`, { method: "POST" }).then(() => router.push(item.kind === "completion" ? "/library" : "/products")).catch(e => setMessage(e instanceof Error ? e.message : String(e)));
      }} />)}
      <Button label={tr("Reload preferences and inbox")} disabled={busy} variant="ghost" onPress={() => void load()} />
      {!!message && <Text accessibilityRole="alert">{tr(message)}</Text>}
    </View>
  </Screen>;
}
