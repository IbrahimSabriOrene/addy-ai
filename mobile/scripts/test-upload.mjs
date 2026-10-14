import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const calls = [];
const context = {
  exports: {}, URL, Blob, setTimeout,
  process: { env: { EXPO_PUBLIC_API_URL: "https://api.example.test/v1" } },
  require(name) {
    if (name === "react-native") return { Platform: { OS: "web" } };
    if (name === "@/lib/auth") return { getToken: async () => "secret" };
    if (name === "expo-file-system/legacy") return new Proxy({}, { get(_, key) { if (key === "__esModule") return true; throw Error("Native filesystem used on web"); } });
    if (name === "./mock") return {};
    throw Error(name);
  },
  async fetch(url, init) {
    calls.push({ url, init });
    if (url === "blob:photo") return { ok: true, blob: async () => new Blob(["image"], { type: "image/png" }) };
    if (url.endsWith("/presign")) return { ok: true, json: async () => ({ uploadUrl: "https://storage.example.test/upload", assetKey: "asset", method: "PUT", headers: { "Content-Type": "image/png" } }) };
    return { ok: true, status: 200, json: async () => ({ id: "job" }) };
  },
};
vm.runInNewContext(source, context);
await context.exports.api.createJob({ imageUri: "blob:photo", platforms: ["reels"], fastMode: true });
const presign = calls.find(call => call.url.endsWith("/presign"));
assert.equal(JSON.parse(presign.init.body).mimeType, "image/png");
assert.equal(JSON.parse(presign.init.body).sizeBytes, 5);
const upload = calls.find(call => call.url.startsWith("https://storage"));
assert.equal(upload.init.method, "PUT");
assert.equal(upload.init.headers.Authorization, undefined);
assert.equal(upload.init.headers["Content-Type"], "image/png");
assert.ok(calls.findIndex(call => call.url.endsWith("/complete")) < calls.findIndex(call => call.url.endsWith("/jobs")));
console.log("Web upload contract passed");
