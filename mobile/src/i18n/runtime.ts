import core from "./messages-core";
import campaign from "./messages-campaign";
import account from "./messages-account";
import billing from "./messages-billing";

export type Locale = "en" | "tr" | "pt-BR" | "es";
export const LOCALES: Locale[] = ["en", "tr", "pt-BR", "es"];
export const LANGUAGE_NAMES: Record<Locale, string> = { en: "English", tr: "Türkçe", "pt-BR": "Português (Brasil)", es: "Español" };
export const LOCALE_STORAGE_KEY = "addy:ui-language";
const messages: Record<string, [string, string, string]> = { ...core, ...campaign, ...account, ...billing };
export function normalizeLocale(value: unknown): Locale {
  const code = typeof value === "string" ? value.replace(/_/g, "-").toLowerCase() : "";
  if (code === "tr" || code.startsWith("tr-")) return "tr";
  if (code === "es" || code.startsWith("es-")) return "es";
  if (code === "pt" || code === "pt-br") return "pt-BR";
  return "en";
}
export function deviceLocale(): Locale {
  try { return normalizeLocale(Intl.DateTimeFormat().resolvedOptions().locale); } catch { return "en"; }
}
let currentLocale: Locale = deviceLocale();
export function setCurrentLocale(locale: Locale) { currentLocale = locale; }
export function getLocale(): Locale { return currentLocale; }
export function translate(source: string, params?: Record<string, string | number>, locale: Locale = currentLocale): string {
  const index = LOCALES.indexOf(locale) - 1;
  const template = index >= 0 && Object.prototype.hasOwnProperty.call(messages, source) ? messages[source][index] || source : source;
  return template.replace(/\{(\w+)\}/g, (match, key: string) => params && Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match);
}
