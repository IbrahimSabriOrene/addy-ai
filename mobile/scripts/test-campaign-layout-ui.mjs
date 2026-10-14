import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const values = [], calls = [];
let index = 0, mounted = false, disabled = true, responseVersion = 3;
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const slot = index++; if (!(slot in values)) values[slot] = initial; return [values[slot], value => { values[slot] = value; }]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
  if (name === "react") return React;
  if (name === "react-native") return { Image: "Image", View: "View" };
  if (name === "@/api/client") return { req: async (path, init) => {
    calls.push({ path, init });
    return { version: responseVersion, state: init ? "ready" : "not_generated", outputs: init ? {
      story: { url: "/private/story", width: 1080, height: 1920, offer: "15%", cta: "Shop" },
      feed: { url: "/private/feed", width: 1080, height: 1080, offer: "15%", cta: "Shop" },
    } : {} };
  } };
  return { Button: "Button", Text: "Text" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/CampaignLayouts.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { index = 0; return context.exports.CampaignLayouts({ campaignId: "campaign", version: 3, disabled }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(node => node.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
assert.equal(calls.length, 1);
assert.equal(button("Prepare story and feed images").props.disabled, true);
button("Prepare story and feed images").props.onPress(); await settle();
assert.equal(calls.length, 1, "Unsaved edits cannot trigger rendering");
disabled = false;
button("Prepare story and feed images").props.onPress(); await settle();
assert.deepEqual(JSON.parse(calls.at(-1).init.body), { expectedVersion: 3 });
assert.equal(nodes(render()).filter(node => typeof node.type === "function").length, 2);
assert.equal(button("Prepare story and feed images"), undefined);
responseVersion = 4;
button("Refresh campaign images").props.onPress(); await settle();
assert.equal(nodes(render()).filter(node => typeof node.type === "function").length, 0, "Mismatched results are not shown as current");
assert.ok(JSON.stringify(render()).includes("Campaign changed"));
assert.ok(calls.every(call => call.path === "/v1/campaigns/campaign/layouts"));
console.log("Layout UI renders only saved versions, requests explicitly and hides mismatched outputs");
