import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const values = [], calls = [];
let index = 0, disabled = true, fail = true;
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const slot = index++; if (!(slot in values)) values[slot] = initial; return [values[slot], value => { values[slot] = value; }]; },
  useRef(initial) { const slot = index++; if (!(slot in values)) values[slot] = { current: initial }; return values[slot]; },
};
const context = { exports: {}, Error, process: { env: { EXPO_PUBLIC_API_URL: "https://api.example/v1" } }, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
  if (name === "react") return React;
  if (name === "react-native") return { View: "View" };
  if (name === "@/api/client") return { req: async (path, init) => {
    calls.push({ path, init });
    await new Promise(resolve => setImmediate(resolve));
    if (!init) return path.includes("beforeVersion=2")
      ? { items: [{ version: 1, jobState: "delivered" }], nextBeforeVersion: null }
      : { items: [{ version: 2, jobState: "awaiting_user_decision" }], nextBeforeVersion: 2 };
    if (fail) throw Error("Speech not verified free of old offers");
    return { version: 3, outputs: { video: { url: "/private/video", sourceVersion: 1, offer: "15%", cta: "Shop" } } };
  } };
  return { Button: "Button", Text: "Text", CampaignMediaPreview: "Preview", ExportMedia: "Export" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/CampaignVideoEdit.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { index = 0; return context.exports.CampaignVideoEdit({ campaignId: "campaign", version: 3, disabled }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(node => node.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
button("Choose a delivered video").props.onPress(); await settle();
assert.equal(calls.length, 0);
disabled = false;
button("Choose a delivered video").props.onPress(); await settle();
assert.equal(button("Use video from version 2"), undefined);
assert.equal(button("Use video from version 1"), undefined);
button("Load older videos").props.onPress(); await settle();
assert.ok(calls.at(-1).path.endsWith("&beforeVersion=2"));
assert.equal(button("Load older videos"), undefined);
const choose = button("Use video from version 1");
choose.props.onPress(); choose.props.onPress(); await settle();
assert.equal(calls.filter(call => call.init).length, 1);
assert.ok(JSON.stringify(render()).includes("Speech not verified"));
fail = false;
button("Use video from version 1").props.onPress(); await settle();
assert.deepEqual(JSON.parse(calls.at(-1).init.body), { expectedVersion: 3, sourceVersion: 1 });
assert.ok(nodes(render()).some(node => node.type === "Export" && node.props.mimeType === "video/mp4"));
assert.ok(calls.every(call => !call.path.endsWith("/generate")));
console.log("Video edit UI: unsaved guard, delivered sources only, duplicate click guard, failed-review retry and MP4 export passed");
