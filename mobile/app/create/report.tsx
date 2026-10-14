import { useI18n } from "@/i18n";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React, { useEffect, useRef, useState } from "react";
import { TextInput, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useLocalSearchParams } from "expo-router";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/TopBar";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { req, USE_MOCK } from "@/api/client";
import { useTheme } from "@/theme/ThemeProvider";

const REASONS = { unsafe_content: "Unsafe or offensive content", product_accuracy: "Product looks wrong", rights: "Copyright or other rights", other: "Something else" };
type Report = { id: string; status: string; reason: keyof typeof REASONS; resolution: string };
type Submission = { key: string; body: { reason: keyof typeof REASONS; details: string; expectedResultVersion: string; attemptSequence?: number }; id?: string };

export default function ReportScreen() {
  const { id, version, attempt } = useLocalSearchParams<{ id: string; version: string; attempt?: string }>();
  const { tr } = useI18n();
  const t = useTheme();
  const [reason, setReason] = useState<keyof typeof REASONS>("product_accuracy");
  const [details, setDetails] = useState("");
  const [reports, setReports] = useState<Report[]>([]);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const storageKey = useRef("");
  const sending = useRef(false);

  async function refresh() {
    const response = await req<{ items: Report[] }>(`/v1/jobs/${id}/reports`);
    setReports(response.items);
  }

  useEffect(() => {
    let active = true;
    if (!id || USE_MOCK) return;
    setReady(false); setError("");
    void (async () => {
      try {
        if (attempt !== undefined && (typeof attempt !== "string" || !/^[1-9]\d*$/.test(attempt) || !Number.isSafeInteger(Number(attempt)))) {
          throw Error("This generation attempt is invalid. Open the result again before reporting.");
        }
        const account = await req<{ email: string }>("/v1/account");
        const key = `addy:report:${process.env.EXPO_PUBLIC_API_URL}:${account.email}:${id}:${version}${attempt ? `:attempt:${attempt}` : ""}`;
        const value = await AsyncStorage.getItem(key);
        const saved: Submission | null = value ? JSON.parse(value) : null;
        const response = await req<{ items: Report[] }>(`/v1/jobs/${id}/reports`);
        if (!active) return;
        storageKey.current = key;
        if (saved) { setSubmission(saved); setReason(saved.body.reason); setDetails(saved.body.details); }
        setReports(response.items); setReady(true);
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Could not load reports."); }
    })();
    return () => { active = false; };
  }, [id, version, attempt, loadAttempt]);

  async function send() {
    if (!ready || !version || sending.current) return;
    sending.current = true; setBusy(true); setError("");
    const action = submission ?? { key: `report-${Date.now()}-${Math.random().toString(36).slice(2)}`, body: { reason, details: details.trim(), expectedResultVersion: version, ...(attempt ? { attemptSequence: Number(attempt) } : {}) } };
    try {
      await writeAccountDraft(storageKey.current, JSON.stringify(action));
      setSubmission(action);
      const result = await req<{ id: string }>(`/v1/jobs/${id}/reports`, {
        method: "POST", headers: { "Idempotency-Key": action.key }, body: JSON.stringify(action.body),
      });
      const completed = { ...action, id: result.id };
      await writeAccountDraft(storageKey.current, JSON.stringify(completed));
      setSubmission(completed);
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not send your report. Retry the same report."); }
    finally { sending.current = false; setBusy(false); }
  }

  return <Screen bottomInset={24}>
    <TopBar title={tr('Report this result')} />
    <View style={{ gap: 16, paddingVertical: 16 }}>
      {!id ? <Text>{tr('No result was selected.')}</Text> : USE_MOCK ? <Text>{tr('Reporting is available for results in your connected account.')}</Text> : <>
        <Text>{tr('Tell us what needs review. Your report is linked to this result and is visible to Addy AI support.')}</Text>
        <Text>{tr('Please leave out passwords, payment details and other sensitive information.')}</Text>
        {Object.entries(REASONS).map(([key, label]) => <Button key={key} label={tr(label)} variant={reason === key ? "primary" : "secondary"}
          disabled={!ready || busy || !!submission} onPress={() => setReason(key as keyof typeof REASONS)} />)}
        <TextInput accessibilityLabel={tr('Report details')} placeholder={tr('What should we look at? (optional)')} maxLength={1000} multiline value={details} onChangeText={setDetails}
          editable={ready && !busy && !submission} placeholderTextColor={t.colors.textSecondary}
          style={{ color: t.colors.text, minHeight: 120, padding: 14, borderWidth: 1, borderColor: t.colors.borderStrong }} />
        {submission?.id ? <Text accessibilityLiveRegion="polite">{tr("Report saved for review. Reference: {id}", { id: submission.id })}</Text> :
          <Button label={tr(submission ? "Retry same report" : "Send report")} disabled={!ready || !version} loading={busy} onPress={() => void send()} />}
        {!version && <Text>{tr('Open the result again to select the version you want to report.')}</Text>}
        {!!error && <Text accessibilityRole="alert">{tr(error)}</Text>}
        <Text variant="heading">{tr('Report status')}</Text>
        {reports.map(report => <View key={report.id} style={{ gap: 8 }}>
          <Text>{tr(REASONS[report.reason])} · {tr(({ open: "Awaiting review", reviewing: "Under review", resolved: "Resolved" } as Record<string, string>)[report.status] || report.status)}</Text>
          {!!report.resolution && <Text>{report.resolution}</Text>}
        </View>)}
        <Button label={tr(ready ? "Refresh report status" : "Reload report form")} variant="secondary" disabled={busy}
          onPress={() => ready ? void refresh().catch(e => setError(e.message)) : setLoadAttempt(value => value + 1)} />
      </>}
    </View>
  </Screen>;
}
