import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const opened = [], alerts = [], routes = [];
let rejectOpen = false;
const context = { __DEV__: false, exports: {}, URL, process: { env: {} }, require(name) {
  if (name === "@/i18n") { const tr = (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])); return { useI18n: () => ({ locale: "en", tr }), translate: tr }; }
  if (name === "expo-router") return { router: { push: target => routes.push(target) } };
  assert.equal(name, "react-native");
  return {
    Platform: { OS: "ios" },
    Linking: { openURL: async url => { if (rejectOpen) throw Error("Unavailable"); opened.push(url); } },
    Alert: { alert: (...args) => alerts.push(args) },
  };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/lib/publicLinks.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, context);
assert.equal(context.exports.TERMS_URL, "");
await context.exports.openPublicLink("https://example.test/terms", "Terms");
assert.deepEqual(opened, ["https://example.test/terms"]);
for (const value of ["", "not a URL", "http://example.test", "javascript:alert(1)", "https://user:pass@example.test", "mailto:help@example.test"]) {
  await context.exports.openPublicLink(value, "Terms");
}
assert.equal(opened.length, 1);
assert.equal(alerts.length, 6);
await context.exports.openPublicLink("mailto:help@example.test", "Support", true);
assert.equal(opened[1], "mailto:help@example.test");
rejectOpen = true;
await context.exports.openPublicLink("https://example.test/terms", "Terms");
assert.equal(alerts.length, 7);
assert.ok(alerts.every(([title, body]) => title === "Terms unavailable" && (body.includes("could not be opened") || body.includes("no published document"))));
console.log("Public links passed: HTTPS, explicit support email, missing/invalid/unsafe URLs and opener failure; no external navigation.");

context.__DEV__ = true;
await context.exports.openPublicLink("", "Terms");
await context.exports.openPublicLink("", "Privacy notice");
assert.deepEqual(routes.map(route => route.params.document), ["terms", "privacy"]);
assert.ok(routes.every(route => route.pathname === "/legal-document"));
await context.exports.openPublicLink("", "Privacy support", true);
assert.equal(routes.length, 2);
const drafts = JSON.parse(readFileSync(new URL("../src/lib/legalDrafts.json", import.meta.url), "utf8"));
for (const draft of Object.values(drafts)) assert.equal(draft.body, readFileSync(new URL(`../../release/${draft.source}`, import.meta.url), "utf8"));
console.log("Draft routes and source document parity passed; release mode never routes to drafts.");
