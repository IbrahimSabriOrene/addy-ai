import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../app/create/generating.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;

async function scenario(state, id = "job-1", pending = false) {
  let slot = 0, mounted = false, cleanup, resolve;
  const values = [], routes = [], requests = [];
  const reference = { current: null };
  const React = { createElement: (type, props, ...children) => ({ type, props, children }),
    useState(initial) { const key = slot++; if (!mounted) values[key] = initial; return [values[key], v => { values[key] = v; }]; },
    useRef: () => reference, useCallback: fn => fn,
    useEffect(fn) { if (!mounted) cleanup = fn(); },
  };
  class AuthError extends Error {}
  const router = { replace: route => routes.push(route) };
  const context = { exports: {}, AbortController, require(name) {
  if (name === "@/i18n") { const tr = (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])); return { useI18n: () => ({ locale: "en", tr }), translate: tr }; }
    if (name === "react") return React;
    if (name === "expo-router") return { useRouter: () => router, useLocalSearchParams: () => ({ id }) };
    if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
    if (name === "@/api/client") return {
      ApiError: class extends Error {}, AuthError,
      pollJob(id, tick, options) {
        requests.push({ id, options });
        if (state === "auth-expired") return Promise.reject(new AuthError());
        const job = { id, state, outputKind: "photo" };
        tick(job);
        return pending ? new Promise(r => { resolve = () => r(job); }) : Promise.resolve(job);
      },
    };
    return new Proxy({}, { get: (_, key) => String(key) });
  } };
  vm.runInNewContext(compiled, context);
  function render() { slot = 0; const tree = context.exports.default(); mounted = true; return JSON.stringify(tree); }
  render();
  await new Promise(r => setImmediate(r));
  return { render, routes, requests, cleanup, resolve };
}

for (const [state, route] of [["delivered", "result"], ["needs_reshoot", "reshoot"], ["awaiting_style_choice", "style"], ["awaiting_user_decision", "decision"]]) {
  const test = await scenario(state);
  assert.deepEqual(test.routes, [`/create/${route}?id=job-1`]);
  test.cleanup();
}
for (const [state, message] of [["aborted", "cancelled"], ["failed", "failed"], ["running", "not ready"]]) {
  const test = await scenario(state);
  assert.equal(test.routes.length, 0);
  assert.ok(test.render().includes(message));
  test.cleanup();
}
const missing = await scenario("delivered", "");
assert.equal(missing.requests.length, 0);
assert.ok(missing.render().includes("No generation was selected"));
missing.cleanup();

const active = await scenario("running", "job-1", true);
assert.ok(active.render().includes("Creating your product photo"));
assert.ok(!active.render().includes("left"), "Do not fabricate time estimates");
active.cleanup();
assert.equal(active.requests[0].options.signal.aborted, true);
active.resolve();
await new Promise(r => setImmediate(r));
assert.equal(active.routes.length, 0, "Unmounted poll must not navigate");
console.log("Generation: gates, terminal states, missing IDs, photo status and cancellation verified");

const expired = await scenario("auth-expired", "job & one");
assert.equal(JSON.stringify(expired.routes), JSON.stringify([{ pathname: "/sign-in", params: { returnTo: "/create/generating?id=job%20%26%20one" } }]));
expired.cleanup();
