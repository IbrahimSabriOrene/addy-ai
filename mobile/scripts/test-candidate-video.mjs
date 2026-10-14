import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

let media = {};
let os = "web";
let playerSource;
const React = { createElement: (type, props, ...children) => ({ type, props, children }) };
const source = ts.transpileModule(readFileSync(new URL("../src/components/CandidateVideo.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;
const context = { exports: {}, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({}), translate: source => source };
  if (name === "react") return React;
  if (name === "react-native") return { Platform: { get OS() { return os; } } };
  if (name === "expo-video") return { VideoView: "VideoView", useVideoPlayer(value) { playerSource = value; return "player"; } };
  if (name === "@/lib/usePrivateMedia") return { usePrivateMedia: () => media };
  return { Text: "Text" };
} };
vm.runInNewContext(source, context);
const render = () => context.exports.CandidateVideo({ url: "https://fixture.invalid/private" });
assert.ok(JSON.stringify(render()).includes("Loading your candidate"));
media = { error: "Access denied" };
assert.ok(JSON.stringify(render()).includes("Access denied"));
media = { source: { uri: "blob:authorized-candidate" } };
assert.equal(render().props.src, media.source.uri);
assert.equal(render().props.controls, true);
assert.equal(render().props.autoPlay, undefined);
os = "ios";
media = { source: { uri: "https://fixture.invalid/private", headers: { Authorization: "Bearer fixture" } } };
const native = render();
assert.equal(native.type(native.props).type, "VideoView");
assert.equal(playerSource, media.source);
console.log("Candidate playback waits for authorized media and retains native request headers");
