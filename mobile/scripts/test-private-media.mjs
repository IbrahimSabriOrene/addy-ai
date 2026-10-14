import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../src/lib/usePrivateMedia.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

async function load(url, { platform = "web", ok = true, deferred = false } = {}) {
  const values = [], calls = [], revoked = [];
  let index = 0, cleanup, release;
  const pending = deferred ? new Promise(resolve => { release = resolve; }) : Promise.resolve();
  class MediaURL extends URL {
    static createObjectURL() { return "blob:private-result"; }
    static revokeObjectURL(value) { revoked.push(value); }
  }
  const context = { exports: {}, URL: MediaURL, process: { env: { EXPO_PUBLIC_API_URL: "https://api.example" } },
    fetch: async (url, options) => { calls.push({ url, options }); await pending; return { ok, blob: async () => ({}) }; },
    require(name) {
      if(name==="./localEdits")return {readLocalEdit:async(email,id)=>{assert.equal(email,"owner@example.com");if(id!=="edit_owned")throw Error("Not this account");return {uri:"blob:local-owned",mimeType:"video/mp4"};}};
      if(name==="@/api/client")return {USE_MOCK:false,req:async()=>({email:"owner@example.com"})};
      if (name === "react") return {
        useState(initial) { const slot = index++; values[slot] = initial; return [initial, value => { values[slot] = value; }]; },
        useEffect(effect) { cleanup = effect(); },
      };
      if (name === "react-native") return { Platform: { OS: platform } };
      if (name === "./auth") return { getToken: async () => "private-token" };
      throw Error(name);
    },
  };
  vm.runInNewContext(compiled, context);
  context.exports.usePrivateMedia(url);
  await new Promise(resolve => setImmediate(resolve));
  return { values, calls, revoked, cleanup: () => cleanup?.(), release,
    settle: () => new Promise(resolve => setImmediate(resolve)) };
}

const privateWeb = await load("https://api.example/v1/exports/1");
assert.equal(privateWeb.calls[0].options.headers.Authorization, "Bearer private-token");
assert.equal(privateWeb.values[0].uri, "blob:private-result");
privateWeb.cleanup();
assert.deepEqual(privateWeb.revoked, ["blob:private-result"]);

for (const platform of ["web", "ios"]) {
  const external = await load("https://samples.example/video.mp4", { platform });
  assert.equal(external.calls.length, 0);
  assert.equal(external.values[0].headers.Authorization, undefined);
  external.cleanup();
}
const native = await load("https://api.example/v1/exports/1", { platform: "ios" });
assert.equal(native.calls.length, 0);
assert.equal(native.values[0].headers.Authorization, "Bearer private-token");
native.cleanup();

const failure = await load("https://api.example/v1/exports/1", { ok: false });
assert.equal(failure.values[0], null);
assert.match(failure.values[1], /Could not load/);
failure.cleanup();

const abandoned = await load("https://api.example/v1/exports/1", { deferred: true });
abandoned.cleanup();
abandoned.release();
await abandoned.settle();
assert.equal(abandoned.values[0], null, "Unmounted requests must not publish media or leak blob URLs");
assert.equal(abandoned.revoked.length, 0);
console.log("Private media: authentication, external origins, cleanup, failures and unmount verified");

const local=await load("addy-edit://edit_owned");
assert.equal(local.calls.length,0);assert.equal(local.values[0].uri,"blob:local-owned");local.cleanup();assert.deepEqual(local.revoked,["blob:local-owned"]);
const foreign=await load("addy-edit://edit_foreign");assert.equal(foreign.values[0],null);assert.match(foreign.values[1],/Could not load media/);
