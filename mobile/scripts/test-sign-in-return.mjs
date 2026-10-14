import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const compile = path => ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true,
} }).outputText;
const returns = { exports: {}, URL };
vm.runInNewContext(compile("src/lib/draftReturn.ts"), returns);
let outcome = "success", returnTo, destination, onboarded = 0;
let confirmed = true, eligibilityFails = false;
const React = { createElement: (type, props, ...children) => ({ type, props, children }), useState: value => [value, () => {}] };
const context = { exports: {}, __DEV__: true, require(name) {
  if (name === "@/i18n") { const tr = (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])); return { useI18n: () => ({ locale: "en", tr }), translate: tr }; }
  if (name === "@/api/client") return { USE_MOCK: false, req: async path => {
    assert.equal(path, "/v1/account/eligibility");
    if (eligibilityFails) throw Error("Offline");
    return { confirmed };
  } };
  if (name === "react") return React;
  if (name === "react-native") return { useWindowDimensions: () => ({ width: 390, height: 844 }), View: "View", Pressable: "Pressable", Linking: {} };
  if (name === "expo-router") return { useLocalSearchParams: () => ({ returnTo }), useRouter: () => ({ replace: value => { destination = value; } }) };
  if (name === "expo-apple-authentication") return {
    AppleAuthenticationScope: { FULL_NAME: "name", EMAIL: "email" },
    signInAsync: async () => { if (outcome === "cancel") throw { code: "ERR_REQUEST_CANCELED" }; return { identityToken: "fixture-token" }; },
  };
  if (name === "@/lib/draftReturn") return returns.exports;
  if (name === "@/lib/onboarding") return { markOnboarded: async () => { onboarded++; } };
  if (name === "@/lib/supabase") return { supabase: { auth: { signInWithIdToken: async value => {
    assert.equal(value.provider, "apple"); assert.equal(value.token, "fixture-token");
    return { data: { session: outcome === "success" ? { access_token: "fixture-session" } : null }, error: null };
  } } } };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {}, isDark: true }) };
  return { Screen: "Screen", Text: "Text", Glow: "Glow", Apple: "Apple", Play: "Play" };
} };
vm.runInNewContext(compile("app/sign-in.tsx"), context);
function buttons(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(buttons);
  return [node, ...(node.children ?? []).flatMap(buttons)];
}
for (const value of ["/create/generating?id=job-1", "/create/campaign?product=p&template=t", "/create/customize?template=t&mode=photo", "https://outside.test", undefined]) {
  returnTo = value; outcome = "success"; destination = null;
  await buttons(context.exports.default()).find(node => node.props?.accessibilityLabel === "Sign in with Apple").props.onPress();
  assert.equal(JSON.stringify(destination), JSON.stringify(returns.exports.draftReturn(value) ?? "/home"));
}
const completed = onboarded;
for (const value of ["cancel", "missing-session"]) {
  outcome = value; destination = null;
  await buttons(context.exports.default()).find(node => node.props?.accessibilityLabel === "Sign in with Apple").props.onPress();
  assert.equal(destination, null); assert.equal(onboarded, completed);
}
for (const failed of [false, true]) {
  outcome = "success"; confirmed = false; eligibilityFails = failed;
  returnTo = "/create/customize?template=t&mode=photo";
  await buttons(context.exports.default()).find(node => node.props?.accessibilityLabel === "Sign in with Apple").props.onPress();
  assert.equal(JSON.stringify(destination), JSON.stringify({ pathname: "/age-check", params: { returnTo } }));
}
console.log("Sign-in return: session, safe destinations, cancellation, recorded eligibility bypass and missing/offline eligibility gate passed");

assert.equal(JSON.stringify(returns.exports.draftReturn("/create/generating?id=job%20%26%20one")), JSON.stringify({ pathname: "/create/generating", params: { id: "job & one" } }));
assert.equal(returns.exports.draftReturn("/create/generating"), null);
assert.equal(returns.exports.draftReturn("/create/generating?id=" + "x".repeat(201)), null);
