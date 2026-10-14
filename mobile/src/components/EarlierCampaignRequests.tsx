import { translate as tr, useI18n } from "@/i18n";
import React, { useEffect, useState } from "react";
import { View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";
import { req } from "@/api/client";
import { Button } from "./Button";
import { Text } from "./Text";

export function EarlierCampaignRequests({ campaignId, currentVersion }: { campaignId: string; currentVersion: number }) {
  useI18n();
  const router = useRouter();
  const [keys, setKeys] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const account = await req<{ email: string }>("/v1/account");
        const prefix = `addy:pack-command:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${campaignId}:`;
        const saved = (await AsyncStorage.getAllKeys()).filter(key => {
          const suffix = key.slice(prefix.length);
          return key.startsWith(prefix) && /^[1-9]\d*$/.test(suffix) && Number.isSafeInteger(Number(suffix)) && Number(suffix) < currentVersion;
        });
        if (active) setKeys(saved.sort((a, b) => Number(b.split(":").pop()) - Number(a.split(":").pop())));
      } catch { if (active) setError(tr("Could not check saved requests from earlier versions. Reopen the campaign to retry.")); }
    })();
    return () => { active = false; };
  }, [campaignId, currentVersion]);
  async function check(storageKey: string) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const version = Number(storageKey.split(":").pop());
      const saved = await AsyncStorage.getItem(storageKey);
      if (!saved) { setKeys(old => old.filter(key => key !== storageKey)); return; }
      const command = JSON.parse(saved);
      if (typeof command.key !== "string" || !command.key || command.body?.expectedVersion !== version || !Number.isInteger(command.body.confirmedCredits) || command.body.confirmedCredits < 1 || command.body.confirmedCredits > 10000) throw Error(tr("Saved request could not be read. Contact support before generating again."));
      const result = await req<{ id?: string; state: string }>(`/v1/campaigns/${campaignId}/generate/close`, {
        method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body),
      });
      if (result.id) {
        await AsyncStorage.setItem(storageKey, JSON.stringify({ ...command, jobId: result.id }));
        router.push({ pathname: "/create/campaign-result", params: { campaign: campaignId, version: String(version) } });
      } else if (result.state === "cancelled") {
        await AsyncStorage.removeItem(storageKey);
        setKeys(old => old.filter(key => key !== storageKey));
        setNotice(tr("Unaccepted request for version {v0} closed. No new generation was started.", { v0: version }));
      } else throw Error(tr("Could not resolve the saved request. Retry the check."));
    } catch (e) { setError(e instanceof Error ? e.message : tr("Could not check saved request.")); }
    finally { setBusy(false); }
  }
  return <View style={{ gap: 12 }}>
    {!!keys.length && <Text>{tr("Earlier saved requests: check to open an accepted result or close an unaccepted request. This does not start a new generation.")}</Text>}
    {keys.map(key => <Button key={key} label={tr("Check saved request for version {v0}", { v0: key.split(":").pop() ?? "" })} disabled={busy} variant="secondary" onPress={() => void check(key)} />)}
    {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{tr(notice)}</Text>}
  </View>;
}
