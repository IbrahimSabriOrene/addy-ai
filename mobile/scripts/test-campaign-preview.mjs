import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let open = false, mediaLoads = 0;
const React = { createElement: (type, props, ...children) => ({ type, props, children }),
  useState: initial => [initial === false ? open : initial, value => { open = typeof value === "function" ? value(open) : value; }] };
const context = { exports: {}, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
  if (name === "react") return React;
  if (name === "react-native") return { View: "View", Image: "Image", Platform: { OS: "web" } };
  if (name === "expo-video") return {};
  if (name === "@/lib/usePrivateMedia") return { usePrivateMedia: url => { mediaLoads++; assert.equal(url, "https://api.test/video"); return { source: { uri: "blob:private" }, error: "" }; } };
  return { Button: "Button", Text: "Text" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/CampaignMediaPreview.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => context.exports.CampaignMediaPreview({ url: "https://api.test/video", video: true, label: "Video with sound" });
let tree = render();
assert.equal(mediaLoads, 0);
assert.equal(tree.children[0], false);
tree.children[1].props.onPress();
tree = render();
assert.equal(tree.children[1].props.label, "Close video with sound");
const child = tree.children[0];
open = false; // Loaded preview's own decodeError state starts false.
const video = child.type(child.props);
assert.equal(mediaLoads, 1);
assert.equal(video.type, "video");
assert.equal(video.props.src, "blob:private");
assert.equal(video.props.autoPlay, false);
assert.equal(video.props.controls, true);
assert.equal(video.props.muted, undefined);
console.log("Campaign previews load on demand and expose user-controlled video playback with sound");
