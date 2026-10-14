import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const catalog = { exports: {} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/i18n/messages-account.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, catalog);
let locale = "en";
const tr = (source, params) => (locale === "tr" ? catalog.exports.default[source]?.[0] || source : source).replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key]));
let state = [], slot = 0, mounted = false, deviceCalls = 0, removed = 0, puts = [];
let preferences = { completion: false, weekly: false, analytics: false, weekday: 0, hour: 10, timezone: "UTC" }, version = 0;
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const index = slot++; if (!(index in state)) state[index] = initial; return [state[index], value => { state[index] = value; }]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, Intl, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale, tr }), translate: tr };
  if (name === "react") return React;
  if (name === "react-native") return { View: "View", Switch: "Switch", TextInput: "TextInput" };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
  if (name === "@/lib/notifications") return { enableDeviceNotifications: async () => { deviceCalls++; }, removeDeviceNotifications: async () => { removed++; } };
  if (name === "@/api/client") return { USE_MOCK: false, req: async (path, options) => {
    if (path.endsWith("notifications")) return { items: [] };
    if (options?.method === "PUT") { const body = JSON.parse(options.body); puts.push(body); assert.equal(body.expectedVersion, version); const { expectedVersion, ...next } = body; preferences = next; version++; }
    return { preferences: structuredClone(preferences), version };
  } };
  return { Button: "Button", Text: "Text", Screen: "Screen", TopBar: "TopBar", router: { push() {} } };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../app/notifications.tsx", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText, context);
const render = () => { slot = 0; return context.exports.default(); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(n => n.props?.label === label);
const control = label => nodes(render()).find(n => n.props?.accessibilityLabel === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
assert.equal(deviceCalls, 0);
assert.equal(control("Weekly campaign reminder").props.value, false);
control("Weekly campaign reminder").props.onValueChange(true);
button("Friday").props.onPress();
control("Reminder hour").props.onChangeText("14");
button("Save preferences").props.onPress(); await settle();
assert.equal(puts[0].locale, "en");
assert.equal(puts[0].weekly, true); assert.equal(puts[0].weekday, 4); assert.equal(puts[0].hour, 14);
assert.equal(deviceCalls, 0, "Saving does not prompt for OS permission");
button("Enable device push after saving").props.onPress(); await settle();
assert.equal(deviceCalls, 1);
control("Weekly campaign reminder").props.onValueChange(false);
button("Save preferences").props.onPress(); await settle();
assert.equal(removed, 1);
assert.equal(button("Enable device push after saving").props.disabled, true);
locale = "tr";
assert.ok(control("Haftalık kampanya hatırlatması"), "Turkish screen uses the real translation catalog");
button(tr("Save preferences")).props.onPress(); await settle();
assert.equal(puts.at(-1).locale, "tr");
assert.equal(deviceCalls, 1, "Language save never asks for OS permission again");
console.log("Engagement: default-off preferences, chosen schedule, separate OS permission and withdrawal passed");

