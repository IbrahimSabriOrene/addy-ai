import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const state = [], calls = [];
let slot = 0, mounted = false, conflict = false, copied;
let saved = { id: "campaign", version: 1, imageVersion: 2, assetKey: "approved-snapshot", brief: { campaignLanguage: "es", offer: "20% off", caption: "Caption", cta: "Shop", color: "#FFFFFF", instructions: "private direction" } };
class ApiError extends Error { constructor() { super("Version changed"); this.status = 409; } }
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const index = slot++; if (!(index in state)) state[index] = initial; return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
  if (name === "react") return React;
  if (name === "react-native") return { View: "View", TextInput: "TextInput" };
  if (name === "expo-clipboard") return { setStringAsync: async text => { copied = text; } };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
  if (name === "@/api/client") return { ApiError, req: async (path, init) => {
    calls.push({ path, init });
    if (!init) return structuredClone(saved);
    if (conflict) throw new ApiError();
    const { expectedVersion, ...brief } = JSON.parse(init.body);
    assert.equal(expectedVersion, saved.version);
    assert.equal(brief.instructions, undefined);
    saved = { ...saved, version: saved.version + 1, brief: { ...saved.brief, ...brief } };
    return structuredClone(saved);
  } };
  return { Button: "Button", Text: "Text", ProductPreview: "ProductPreview" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/ProductCampaigns.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { slot = 0; return context.exports.CampaignDetails({ id: "campaign" }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(node => node.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
assert.equal(nodes(render()).find(node => node.type === "ProductPreview").props.assetKey, "approved-snapshot");
nodes(render()).find(node => node.props?.accessibilityLabel === "Offer").props.onChangeText("15% off");
button("Save campaign text").props.onPress(); await settle();
assert.equal(saved.brief.offer, "15% off");
assert.equal(saved.brief.campaignLanguage, "es", "Editing retains campaign language");
assert.equal(saved.version, 2);
button("Copy caption and CTA").props.onPress(); await settle();
assert.equal(copied, "Caption\nShop");
conflict = true;
button("Save campaign text").props.onPress(); await settle();
assert.equal(button("Save campaign text").props.disabled, true);
saved.version = 3;
button("Reload campaign and discard local edits").props.onPress(); await settle();
conflict = false;
button("Save campaign text").props.onPress(); await settle();
assert.equal(saved.version, 4);
assert.ok(calls.every(call => call.path === "/v1/campaigns/campaign"), "Editing never calls generation or billing");
console.log("Campaign editor preserves snapshot, saves exact fields, copies text and reloads conflicts without generation");
