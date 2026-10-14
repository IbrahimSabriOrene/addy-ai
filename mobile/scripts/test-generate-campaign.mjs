import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let slot = 0, mounted = false, granted = false, lost = true, navigated;
const state = [], storage = new Map(), sent = [];
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const i = slot++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = typeof value === "function" ? value(state[i]) : value; }]; },
  useRef(initial) { const i = slot++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "https://api.test" } }, require(name) {
  if (name === "react") return React;
  if (name === "react-native") return { View: "View" };
  if (name === "expo-router") return { useRouter: () => ({ push: route => { navigated = route; } }) };
  if (name === "@/lib/accountDrafts") return { writeAccountDraft: (...args) => context.require("@react-native-async-storage/async-storage").setItem(...args) };
    if (name === "@react-native-async-storage/async-storage") return { getItem: async key => storage.get(key), setItem: async (key, value) => { storage.set(key, value); } };
  if (name === "@/api/client") return { req: async (path, init) => {
    if (path === "/v1/account") return { email: "merchant@example.com" };
    if (path.endsWith("generation-quote")) return { campaignVersion: 1, available: true, priceCredits: 3, settlement: "Complete pack" };
    if (path.endsWith("ai-consent")) { if (init) granted = true; return { granted, disclosureVersion: "v2", disclosure: "AI transfer disclosure" }; }
    if (path.endsWith("/generate")) {
      assert.ok(storage.size, "Save command before POST"); sent.push(init);
      if (lost) throw Error("Response lost");
      return { id: "job" };
    }
    throw Error(path);
  } };
  return { Button: "Button", Text: "Text" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/GenerateCampaign.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { slot = 0; return context.exports.GenerateCampaign({ campaignId: "campaign", version: 1, disabled: false }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(n => n.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
button("Generate pack · 3 credits").props.onPress(); await settle();
assert.equal(sent.length, 0);
button("Do not allow").props.onPress();
assert.equal(storage.size, 0);
button("Generate pack · 3 credits").props.onPress(); await settle();
button("Allow AI processing and generate").props.onPress(); await settle();
assert.equal(sent.length, 1);
assert.equal(navigated, undefined);
state.length = 0; mounted = false;
render(); await settle();
lost = false;
button("Retry saved generation").props.onPress(); await settle();
assert.equal(sent.length, 2);
assert.equal(sent[0].body, sent[1].body);
assert.equal(sent[0].headers["Idempotency-Key"], sent[1].headers["Idempotency-Key"]);
assert.equal(navigated.pathname, "/create/campaign-result");
assert.equal(JSON.parse([...storage.values()][0]).jobId, "job");
console.log("Campaign Generate requires consent and restores exact saved request after lost response");
