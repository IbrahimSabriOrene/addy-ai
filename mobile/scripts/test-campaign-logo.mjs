import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let state = [], slot = 0, uploads = 0, picks = 0, selected = "old", busy = false, cancelled = false, failed = false;
let release;
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const i = slot++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = value; }]; },
  useRef(initial) { const i = slot++; return state[i] ??= { current: initial }; },
};
const context = { exports: {}, Error, require(name) {
  if (name === "react") return React;
  if (name === "react-native") return { View: "View" };
  if (name === "expo-image-picker") return { launchImageLibraryAsync: async () => { picks++; return { canceled: cancelled, assets: [{ uri: "logo.png" }] }; } };
  if (name === "@/api/client") return { uploadImage: async uri => { assert.equal(uri, "logo.png"); uploads++; await new Promise(resolve => { release = resolve; }); if (failed) throw Error("Upload failed"); return "verified-logo"; } };
  return { Button: "Button", Text: "Text", ProductPreview: "ProductPreview" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/CampaignLogo.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { slot = 0; return context.exports.CampaignLogo({ assetKey: selected, disabled: busy, onChange: key => { selected = key; }, onBusyChange: value => { busy = value; } }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(node => node.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
const press = button("Replace campaign logo").props.onPress;
press(); press(); await settle();
assert.equal(picks, 1); assert.equal(uploads, 1); assert.equal(busy, true); assert.equal(selected, "old");
release(); await settle();
assert.equal(selected, "verified-logo"); assert.equal(busy, false);
failed = true; button("Replace campaign logo").props.onPress(); await settle(); release(); await settle();
assert.equal(selected, "verified-logo"); assert.equal(busy, false);
assert.ok(nodes(render()).some(node => node.props?.accessibilityRole === "alert"));
cancelled = true; button("Replace campaign logo").props.onPress(); await settle();
assert.equal(uploads, 2); assert.equal(selected, "verified-logo");
button("Remove campaign logo").props.onPress();
assert.equal(selected, null);
console.log("Campaign logo uploads once, preserves selection on failure/cancel and removes explicitly.");
