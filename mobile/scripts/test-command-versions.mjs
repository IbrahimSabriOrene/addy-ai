import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const calls = [];
let fail = false;
function loadClient() {
  const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "https://fixture.invalid" } },
    require(name) {
      if (name === "@/lib/auth") return { getToken: async () => "fixture-token" };
      if (name === "react-native") return { Platform: { OS: "web" } };
      return {};
    },
    async fetch(url, init) {
      calls.push({ url, key: init.headers["Idempotency-Key"], body: init.body });
      if (fail) { fail = false; throw new Error("response lost"); }
      return { status: 202, ok: true, json: async () => ({ id: "job", state: "submitted" }) };
    },
  };
  vm.runInNewContext(source, context);
  return context.exports.api;
}
for (const command of [
  (api, version) => api.chooseStyle("job", { direction: "Studio light" }, version),
  (api, version) => api.decide("job", "spend_more", version),
  (api, version) => api.regen("job", version),
]) {
  calls.length = 0;
  fail = true;
  await assert.rejects(command(loadClient(), 7));
  await command(loadClient(), 7); // A fresh client recreates the same command after an ambiguous response.
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(JSON.parse(calls[1].body).expectedVersion, 7);
  await command(loadClient(), 8);
  assert.notEqual(calls[1].key, calls[2].key);
}
console.log("Versioned commands retain identical retry keys and payloads across client reloads");
