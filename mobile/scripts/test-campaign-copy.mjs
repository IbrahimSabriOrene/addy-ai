import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let state = [], index = 0, mounted = false, fail = true;
const storage = new Map(), writes = [], posts = [];
const source = { productId: "product", imageVersion: 2, assetKey: "approved", brief: { campaignLanguage: "pt-BR", offer: "Old offer", caption: "Old caption", cta: "Shop", instructions: "Slow camera", color: "#123456", font: "serif", contact: "shop.example", style: { id: "spin", version: 1 } } };
const react = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const slot = index++; if (!(slot in state)) state[slot] = initial; return [state[slot], value => { state[slot] = typeof value === "function" ? value(state[slot]) : value; }]; },
  useRef(initial) { const slot = index++; return state[slot] ??= { current: initial }; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "fixture" } }, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
  if (name === "react") return react;
  if (name === "react-native") return { View: "View", TextInput: "TextInput" };
  if (name === "expo-router") return { useLocalSearchParams: () => ({ campaign: "source" }), router: { push() {} } };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
  if (name === "@react-native-async-storage/async-storage") return { getItem: async key => storage.get(key) ?? null };
  if (name === "@/lib/accountDrafts") return { writeAccountDraft: async (key, value) => { storage.set(key, value); writes.push(value); } };
  if (name === "@/api/client") return { req: async (path, init) => {
    if (path === "/v1/account") return { email: "owner@example.com" };
    if (!init) return structuredClone(source);
    assert.equal(path, "/v1/campaigns", "Copy must never submit a paid generation");
    assert.ok(writes.length, "Persist before submission");
    posts.push({ key: init.headers["Idempotency-Key"], body: JSON.parse(init.body) });
    if (fail) throw Error("Lost response");
    return { id: "copy" };
  } };
  return { Button: "Button", Text: "Text", TopBar: "TopBar", Screen: "Screen", ProductPreview: "ProductPreview" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../app/create/campaign-copy.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { index = 0; return context.exports.default(); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(node => node.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
assert.equal(button("Save campaign copy · no credits").props.disabled, true);
button("I reviewed the offer, dates and copy").props.onPress();
nodes(render()).find(n => n.props?.accessibilityLabel === "Offer for the new campaign").props.onChangeText("New offer");
assert.equal(button("Save campaign copy · no credits").props.disabled, true, "Editing requires reviewing again");
button("I reviewed the offer, dates and copy").props.onPress();
button("Save campaign copy · no credits").props.onPress(); await settle();
assert.equal(posts.length, 1);
assert.equal(posts[0].body.offer, "New offer");
assert.equal(posts[0].body.imageVersion, 2);
assert.equal(posts[0].body.font, "serif");
assert.equal(posts[0].body.campaignLanguage, "pt-BR", "Copy retains the campaign language");
assert.equal(posts[0].body.style, undefined);
state = []; mounted = false; render(); await settle();
fail = false;
button("Retry same copy").props.onPress(); await settle();
assert.deepEqual(posts[0], posts[1], "Restart must reuse the original command");
assert.ok(button("Open copied campaign"));
assert.equal(source.brief.offer, "Old offer");
console.log("Campaign copy reviews old offers, snapshots the image/brand and retries without paid generation");
