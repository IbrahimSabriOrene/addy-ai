import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let job;
const React = { createElement: (type, props, ...children) => ({ type, props, children }),
  useEffect() {}, useState: value => [value, () => {}], useMemo: fn => fn() };
const source = ts.transpileModule(readFileSync(new URL("../app/create/result.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;
const context = { exports: {}, require(name) {
  if (name === "@/i18n") { const tr = (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])); return { useI18n: () => ({ locale: "en", tr }), translate: tr }; }
  if (name === "react") return React;
  if (name === "expo-router") return { useRouter: () => ({}), useLocalSearchParams: () => ({ id: "real-job" }) };
  if (name === "react-native-safe-area-context") return { useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({}) };
  if (name === "@/api/hooks") return { useJob: () => job, useWallet: () => ({}), useRegen: () => ({}) };
  if (name === "@/api/mock") return { MOCK_RESULT: { state: "delivered", exports: [{ url: "SAMPLE-DO-NOT-SHOW", platform: "tiktok" }] } };
  if (name === "@/api/client") return { USE_MOCK: false };
  return new Proxy({}, { get: (_, key) => String(key) });
} };
vm.runInNewContext(source, context);
for (const [state, expected] of [
  [{ isPending: true }, "Loading your result"],
  [{ isError: true, error: new Error("Offline") }, "Could not load this result"],
  [{ data: { state: "generating", exports: [] } }, "not ready yet"],
]) {
  job = { ...state, refetch() {} };
  const rendered = JSON.stringify(context.exports.default());
  assert.ok(rendered.includes(expected));
  assert.ok(!rendered.includes("SAMPLE-DO-NOT-SHOW"));
  assert.ok(!rendered.includes("Your ad is ready"));
}
console.log("Real result states do not display sample output");
