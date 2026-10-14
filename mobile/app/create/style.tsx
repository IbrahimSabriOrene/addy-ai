import { useI18n, translate } from "@/i18n";
import React, { useState } from "react";
import { View, Pressable } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Screen } from "@/components/Screen";
import { Text } from "@/components/Text";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { MediaPlaceholder } from "@/components/MediaPlaceholder";
import { Check, Play, Refresh } from "@/components/Icons";
import { useTheme } from "@/theme/ThemeProvider";
import { useJob, useChooseStyle } from "@/api/hooks";
import type { StyleCandidate } from "@/api/types";

export default function StyleScreen() {
  useI18n();
  const t = useTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const job = useJob(id ?? "");
  const chooseStyle = useChooseStyle(id ?? "");

  const candidates: StyleCandidate[] = job.data?.candidates ?? [];
  const [selected, setSelected] = useState(0);

  const chosen = candidates[selected];

  const onMake = async () => {
    if (!chosen || !job.data?.version) return;
    try {
      await chooseStyle.mutateAsync({ choice: chosen.id, expectedVersion: job.data.version });
      router.replace(`/create/generating?id=${id}`);
    } catch { /* Keep the displayed version for an exact retry. */ }
  };

  return (
    <Screen bottomInset={12}>
      {/* Header */}
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingTop: 4 }}>
        <Text variant="title">{translate("Pick a direction")}</Text>
      </View>
      <Text variant="bodySm" color={t.colors.textSecondary} style={{ marginTop: 4 }}>
        {translate("Choose a style for this generation.")}</Text>

      {/* Candidates */}
      <View style={{ marginTop: 18, gap: 14, flex: 1 }}>
        {candidates.map((c, i) => (
          <CandidateRow
            key={c.id}
            candidate={c}
            selected={i === selected}
            dimmed={false}
            onPress={() => setSelected(i)}
          />
        ))}
      </View>

      {/* Actions */}
      <View style={{ gap: 11, paddingBottom: 34 }}>
        <Button
          label={!chosen ? translate("Make my ad") : translate("Make {name}", { name: chosen.name })}
          disabled={!chosen || !job.data?.version}
          loading={chooseStyle.isPending}
          onPress={onMake}
        />
        {chooseStyle.isError && <Text accessibilityRole="alert">{translate("Could not apply this choice. Retry the same choice, or reload to review the current generation.")}</Text>}
        {(chooseStyle.isError || !job.data?.version) && <Button label={translate("Reload generation")} variant="secondary" onPress={() => job.refetch()} />}
          <Button
            variant="ghost"
            label={translate("Reload available styles")}
            icon={<Refresh color={t.colors.textSecondary} />}
            onPress={() => job.refetch()}
          />
      </View>
    </Screen>
  );
}

function CandidateRow({
  candidate,
  selected,
  dimmed,
  onPress,
}: {
  candidate: StyleCandidate;
  selected: boolean;
  dimmed: boolean;
  onPress: () => void;
}) {
  useI18n();
  const t = useTheme();
  return (
    <Card selected={selected} onPress={onPress} style={{ opacity: dimmed ? 0.55 : 1, padding: 12 }} radius={t.radius.xxl}>
      <View style={{ flexDirection: "row", gap: 14 }}>
        <MediaPlaceholder source={candidate.motionRef ? { uri: candidate.motionRef } : undefined} tone="teal" label={translate("Preview unavailable")} style={{ width: 74, height: 104, borderRadius: 13 }}>
          {selected && (
            <View
              style={{
                position: "absolute",
                bottom: 7,
                width: 24,
                height: 24,
                borderRadius: 12,
                backgroundColor: "rgba(255,255,255,0.85)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Play size={11} color={t.colors.accentInk} />
            </View>
          )}
        </MediaPlaceholder>

        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text variant="subheading">{candidate.name}</Text>
            {selected && (
              <View
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  backgroundColor: t.colors.accent,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Check size={12} color={t.colors.accentInk} strokeWidth={3.5} />
              </View>
            )}
          </View>
          <Text variant="caption" color={t.colors.textSecondary} style={{ marginTop: 2 }}>
            {candidate.oneLiner}
          </Text>
          <View
            style={{
              marginTop: 9,
              paddingHorizontal: 10,
              paddingVertical: 7,
              backgroundColor: t.colors.surfaceRaised,
              borderRadius: t.radius.sm,
            }}
          >
            <Text variant="label" family={t.fonts.bodyReg} color={t.colors.textSecondary} style={{ fontSize: 11.5, lineHeight: 16 }}>
              “{candidate.captionPreview}”
            </Text>
          </View>
        </View>
      </View>
    </Card>
  );
}
