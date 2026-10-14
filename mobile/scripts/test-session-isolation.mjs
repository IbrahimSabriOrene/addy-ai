import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function compile(path) {
  return ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
}
let session = { access_token: "user-a-token", user: { id: "user-a" } };
const stored = new Map();
let callback, unsubscribed = false, refuseSignOut = false;
const supabase = { auth: {
  getSession: async () => ({ data: { session } }),
  signOut: async options => { assert.equal(options.scope, "local"); if (!refuseSignOut) session = null; return { error: refuseSignOut ? Error("Offline") : null }; },
  onAuthStateChange: listener => { callback = listener; return { data: { subscription: { unsubscribe: () => { unsubscribed = true; } } } }; },
} };
const auth = { exports: {}, require(name) {
  if (name === "./supabase") return { supabase };
  if (name === "expo-secure-store") return {
    getItemAsync: async key => stored.get(key), setItemAsync: async (key, value) => stored.set(key, value),
    deleteItemAsync: async key => stored.delete(key),
  };
  throw Error(name);
} };
vm.runInNewContext(compile("../src/lib/auth.ts"), auth);
await auth.exports.setTokens("legacy-user-token", "legacy-refresh");
assert.equal(await auth.exports.getToken(), "user-a-token");
session.access_token = "rotated-user-a-token";
assert.equal(await auth.exports.getToken(), "rotated-user-a-token");
session = { access_token: "user-b-token", user: { id: "user-b" } };
assert.equal(await auth.exports.getToken(), "user-b-token");
refuseSignOut = true;
await assert.rejects(auth.exports.clearTokens(), /Offline/);
assert.equal(stored.size, 0, "Legacy credentials removed even if session sign-out fails");
refuseSignOut = false;
await auth.exports.clearTokens();
assert.equal(await auth.exports.getToken(), null, "Signed-out sessions must never fall back to old credentials");

let value, initialized = false, cleanup, clears = 0;
const React = { Fragment: "Fragment", createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { if (!initialized) value = initial; return [value, next => { value = next; }]; },
  useEffect(effect) { if (!initialized) cleanup = effect(); },
};
const boundary = { exports: {}, require(name) {
  if (name === "react") return React;
  if (name === "@/lib/supabase") return { supabase };
  if (name === "@tanstack/react-query") return { useQueryClient: () => ({ clear: () => { clears++; } }) };
  throw Error(name);
} };
vm.runInNewContext(compile("../src/components/SessionBoundary.tsx"), boundary);
function render() { const result = boundary.exports.SessionBoundary({ children: "private-screen" }); initialized = true; return result; }
assert.equal(render(), null, "Do not render private views before the initial session is known");
callback("INITIAL_SESSION", { user: { id: "user-a" } });
assert.equal(render().props.key, "user-a");
assert.equal(clears, 1);
callback("TOKEN_REFRESHED", { user: { id: "user-a" } });
assert.equal(clears, 1, "Token refresh for the same account retains its screen");
callback("SIGNED_IN", { user: { id: "user-b" } });
assert.equal(render().props.key, "user-b", "Changing the React key unmounts the previous user's local screen state");
assert.equal(clears, 2);
callback("SIGNED_OUT", null);
assert.equal(render().props.key, "signed-out");
assert.equal(clears, 3);
cleanup();
assert.equal(unsubscribed, true);
console.log("Session isolation: current tokens, real sign-out, failure handling, cache reset and screen identity verified");
