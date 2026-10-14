import React, { useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { useI18n } from "@/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { Button } from "./Button";
import { Text } from "./Text";

const swatches = ["#FFFFFF", "#16161B", "#00C2A8", "#F4D9C6", "#F8D7E8", "#C9DEF5", "#E6AC3D", "#D8E6CE"];
export function ColorField({ value, onChange, disabled, label }: { value: string; onChange: (value: string) => void; disabled: boolean; label: string }) {
  const { tr } = useI18n(), t = useTheme();
  const [custom, setCustom] = useState(false);
  return <View style={{ gap: 8 }}>
    <Text>{tr("Color")}</Text>
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {swatches.map(color => <Pressable key={color} accessibilityRole="radio" aria-checked={value.toUpperCase() === color} accessibilityLabel={`${tr("Color")} ${color}`} accessibilityState={{ checked: value.toUpperCase() === color, disabled }}
        disabled={disabled} onPress={() => onChange(color)} style={{ width: 44, height: 44, borderRadius: 12, borderWidth: value.toUpperCase() === color ? 3 : 1, borderColor: value.toUpperCase() === color ? t.colors.accent : t.colors.borderStrong, padding: 5 }}>
        <View style={{ flex: 1, backgroundColor: color, borderRadius: 6 }} />
      </Pressable>)}
    </View>
    <Button label={`${tr("Custom color")} · ${value}`} variant="ghost" onPress={() => setCustom(!custom)} />
    {(custom || !/^#[0-9a-f]{6}$/i.test(value)) && <TextInput accessibilityLabel={label} value={value} onChangeText={onChange} editable={!disabled} maxLength={7} autoCapitalize="none" autoCorrect={false}
      style={{ color: t.colors.text, minHeight: 44, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: t.colors.borderStrong }} />}
  </View>;
}
