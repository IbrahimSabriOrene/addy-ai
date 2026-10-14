import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
let os = "ios", token = "token", status = 200, shared = 0, deleted = 0, fetched = 0, clicked = 0, revoked = 0;
const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "https://api.test" } },
  URL: class extends URL { static createObjectURL() { return "blob:file"; } static revokeObjectURL() { revoked++; } },
  setTimeout: fn => fn(), document: { body: { appendChild() {} }, createElement: () => ({ click() { clicked++; }, remove() {} }) },
  fetch: async (url, options) => { fetched++; assert.equal(options.headers.Authorization, "Bearer token"); assert.equal(options.redirect, "error"); return { ok: status === 200, headers: new Headers({ "content-type": "image/png" }), blob: async () => ({ size: 20 }) }; },
  require(name) {
    if(name==="./localEdits")return {readLocalEdit:async()=>{throw Error("No local file for this account.");}};
    if(name==="@/api/client")return {USE_MOCK:false,req:async()=>({email:"owner@example.com"})};
    if (name === "react-native") return { Platform: { get OS() { return os; } } };
    if (name === "./auth") return { getToken: async () => token };
    if (name === "expo-sharing") return { isAvailableAsync: async () => true, shareAsync: async (url, options) => { assert.ok(url.startsWith("file:cache/export-")); assert.equal(options.mimeType, "image/png"); shared++; } };
    if (name === "expo-file-system/legacy") return { cacheDirectory: "file:cache/", makeDirectoryAsync: async () => {},
      downloadAsync: async (url, destination, options) => { fetched++; assert.equal(options.headers.Authorization, "Bearer token"); return { status, headers: { "Content-Type": "image/png" } }; },
      getInfoAsync: async () => ({ exists: true, size: 20 }), deleteAsync: async () => { deleted++; },
    };
    throw Error(name);
  },
};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/lib/exportPrivateMedia.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, context);
const run = (url = "https://api.test/v1/private") => context.exports.exportPrivateMedia(url, "story.png", "image/png");
await assert.rejects(run("https://foreign.test/private")); assert.equal(fetched, 0);
await assert.rejects(run("addy-edit://edit_missing"),/No local file/);
token = null; await assert.rejects(run()); assert.equal(fetched, 0); token = "token";
await run(); assert.equal(shared, 1); assert.equal(deleted, 1);
status = 403; await assert.rejects(run()); assert.equal(shared, 1); assert.equal(deleted, 2);
os = "web"; status = 200; await run(); assert.equal(clicked, 1); assert.equal(revoked, 1);
status = 403; await assert.rejects(run()); assert.equal(clicked, 1);
console.log("Private exports require same-origin authentication, reject failed downloads and clean native/web temporary files");
