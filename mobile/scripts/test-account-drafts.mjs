import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const a = "addy:create:https://api.example:a@example.com:one";
const b = "addy:create:https://api.example:b@example.com:one";
const stored = new Map([[b, "keep"], ["purchase:pending", "keep"]]);
let release, started;
const began = new Promise(resolve => { started = resolve; });
const paused = new Promise(resolve => { release = resolve; });
const storage = {
  getAllKeys: async () => [...stored.keys()],
  multiRemove: async keys => { keys.forEach(key => stored.delete(key)); },
  setItem: async (key, value) => { if (key === a) { started(); await paused; } stored.set(key, value); },
};
const source = ts.transpileModule(readFileSync(new URL("../src/lib/accountDrafts.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;
const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "https://api.example" } }, require: name => name === "./localEdits" ? {clearLocalEdits:async email=>{assert.equal(email,"a@example.com");}} : storage };
vm.runInNewContext(source, context);
const { writeAccountDraft, clearAccountDrafts } = context.exports;
const pending = writeAccountDraft(a, "late private data");
await began;
const deletion = clearAccountDrafts("a@example.com");
const late = assert.rejects(writeAccountDraft(a, "must not recreate"), /Draft saving stopped/);
release();
await Promise.all([pending, deletion, late]);
assert.equal(stored.has(a), false);
assert.equal(stored.get(b), "keep");
assert.equal(stored.get("purchase:pending"), "keep");
await writeAccountDraft(b, "other account still works");
assert.equal(stored.get(b), "other account still works");
await clearAccountDrafts("a@example.com");
assert.equal(stored.has(a), false);
console.log("Draft deletion drains an in-flight write, rejects late recreation, preserves other accounts and purchase records");
