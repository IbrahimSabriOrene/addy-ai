import { useI18n } from "@/i18n";
import React from "react";
import { Tabs } from "expo-router";
import { TabBar } from "@/components/TabBar";

export default function TabsLayout() {
  const { tr } = useI18n();
  return (
    <Tabs
      initialRouteName="home"
      screenOptions={{ headerShown: false }}
      tabBar={(props) => <TabBar {...props} />}
    >
      <Tabs.Screen name="home" options={{ title: tr("Home") }} />
      <Tabs.Screen name="library" options={{ title: tr("Library") }} />
      <Tabs.Screen name="account" options={{ title: tr("Account") }} />
    </Tabs>
  );
}
