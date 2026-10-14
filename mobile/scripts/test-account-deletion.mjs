import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../app/delete-account.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;
class ApiError extends Error { constructor(status) { super(`HTTP ${status}`); this.status = status; } }
let hooks = [], cursor = 0, events = [], cleanupFails = true, accepted = false, loseResponse = true;
const React = {
  createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }),
  useState(initial) { const i = cursor++; if (!(i in hooks)) hooks[i] = initial; return [hooks[i], value => { hooks[i] = value; }]; },
};
const context = { Error, exports: {}, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en", tr: (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])) }) };
  if (name === "react") return React;
  if (name === "react-native") return { TextInput: "TextInput", View: "View" };
  if (name === "expo-router") return { useRouter: () => ({ back() {}, replace() {} }) };
  if (name === "@tanstack/react-query") return { useQueryClient: () => ({ cancelQueries: async () => {}, clear: () => events.push("cache-clear") }) };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
  if (name === "@/lib/auth") return { clearTokens: async () => {} };
  if (name === "@/lib/accountDrafts") return { clearAccountDrafts: async email => {
    assert.equal(email, "owner@example.com"); events.push("cleanup"); if (cleanupFails) throw Error("Storage unavailable");
  } };
  if (name === "@/api/client") return { ApiError, req: async (path, options) => {
    events.push(path);
    if (path === "/v1/account") { if (accepted) throw new ApiError(410); return { email: "owner@example.com" }; }
    assert.equal(options.method, "POST"); assert.equal(JSON.parse(options.body).confirmation, "DELETE");
    accepted = true;
    if (loseResponse) { loseResponse = false; throw Error("Lost response"); }
    return { state: "requested" };
  } };
  if (name.startsWith("@/components/")) { const key = name.split("/").at(-1); return { [key]: key }; }
  throw Error(name);
} };
vm.runInNewContext(source, context);
function render() { cursor = 0; return context.exports.default(); }
function find(node, predicate) {
  if (!node || typeof node !== "object") return;
  if (predicate(node)) return node;
  for (const child of (node.children ?? []).flat(Infinity)) { const found = find(child, predicate); if (found) return found; }
}
async function submit() {
  let tree = render(); find(tree, n => n.type === "TextInput").props.onChangeText("DELETE"); tree = render();
  find(tree, n => n.props.label === "Request account deletion").props.onPress();
  await new Promise(resolve => setImmediate(resolve));
}
await submit();
assert.deepEqual(events, ["/v1/account", "cleanup"]);
assert.equal(accepted, false, "Storage failure must prevent remote deletion");
cleanupFails = false; events = [];
await submit();
assert.deepEqual(events, ["/v1/account", "cleanup", "/v1/account/deletion"]);
assert.equal(accepted, true);
assert.match(hooks[3], /Lost response/);
hooks = []; events = []; // Simulate restarting the screen after the accepted request's response was lost.
await submit();
assert.deepEqual(events, ["/v1/account", "/v1/account/deletion", "cache-clear"]);
assert.equal(hooks[1], "requested");
assert.ok(find(render(), n => n.props.label === "Sign out of this device"));
console.log("Deletion screen: cleanup failure blocks POST; cleanup precedes deletion; lost-response restart replays after 410");

