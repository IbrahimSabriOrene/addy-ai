import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let slot = 0, mounted = false, copied, failure = false;
const state = [], calls = [];
let response = { campaignId: "campaign", campaignVersion: 1, state: "incomplete", outputs: {
  cleanImage: { state: "ready", url: "/image", mimeType: "image/jpeg" },
  video: { state: "unavailable" }, story: { state: "pending" }, feed: { state: "pending" },
  copy: { state: "ready", caption: "Caption", cta: "Shop" },
} };
class ApiError extends Error { status = 404; }
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const index = slot++; if (!(index in state)) state[index] = initial; return [state[index], value => { state[index] = value; }]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "https://api.test/v1" } }, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
  if (name === "react") return React;
  if (name === "react-native") return { View: "View" };
  if (name === "expo-clipboard") return { setStringAsync: async value => { copied = value; } };
  if (name === "@/api/client") return { ApiError, req: async path => { calls.push(path); if (failure) throw new ApiError(); return structuredClone(response); } };
  return { Button: "Button", Text: "Text", ExportMedia: "ExportMedia" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/CampaignResults.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { slot = 0; return context.exports.CampaignResults({ campaignId: "campaign", version: 1 }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(n => n.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
const exports = nodes(render()).filter(n => n.type === "ExportMedia");
assert.equal(exports.length, 1);
assert.equal(exports[0].props.mimeType, "image/jpeg");
assert.equal(exports[0].props.url, "https://api.test/image");
button("Copy pack caption and CTA").props.onPress(); await settle();
assert.equal(copied, "Caption\nShop");
response.campaignVersion = 2;
button("Refresh campaign pack").props.onPress(); await settle();
assert.equal(nodes(render()).filter(n => n.type === "ExportMedia").length, 0);
assert.ok(nodes(render()).some(n => n.props?.accessibilityRole === "alert"));
failure = true;
button("Refresh campaign pack").props.onPress(); await settle();
assert.ok(JSON.stringify(render()).includes("No pack has been generated"));
assert.ok(calls.every(path => path === "/v1/campaigns/campaign/generations/1"));
console.log("Campaign results hide unavailable/stale files, export ready media and copy reviewed text without generation");
