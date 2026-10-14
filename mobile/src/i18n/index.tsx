import React, { createContext, useContext, useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { deviceLocale, getLocale, setCurrentLocale, translate, LOCALES, LOCALE_STORAGE_KEY, type Locale } from "./runtime";
export * from "./runtime";
const I18nContext = createContext({ locale: getLocale(), setLocale: async (_locale: Locale) => {}, tr: translate });
export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, updateLocale] = useState(getLocale());
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(LOCALE_STORAGE_KEY).then(saved => {
      if (active) { const next = saved && LOCALES.includes(saved as Locale) ? saved as Locale : deviceLocale(); setCurrentLocale(next); updateLocale(next); }
    }).catch(() => {}).finally(() => { if (active) setReady(true); });
    return () => { active = false; };
  }, []);
  const setLocale = async (next: Locale) => {
    if (!LOCALES.includes(next)) return;
    await AsyncStorage.setItem(LOCALE_STORAGE_KEY, next);
    setCurrentLocale(next);
    updateLocale(next);
  };
  if (!ready) return null;
  return <I18nContext.Provider value={{ locale, setLocale, tr: (source, params) => translate(source, params, locale) }}>{children}</I18nContext.Provider>;
}
export function useI18n() { return useContext(I18nContext); }
