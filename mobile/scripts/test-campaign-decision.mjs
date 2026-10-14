import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const code = ts.transpileModule(readFileSync(new URL("../src/components/CampaignDecision.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;
for (const action of ["accept", "abort", "spend_more"]) {
  let slot = 0, mounted = false, lost = true, resolved = 0;
  const state = [], storage = new Map(), sent = [];
  const React = { createElement: (type, props, ...children) => ({ type, props, children }),
    useState(initial) { const i = slot++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = value; }]; },
    useRef(initial) { const i = slot++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
    useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
  };
  const context = { exports: {}, process: { env: { EXPO_PUBLIC_API_URL: "https://api.test" } }, require(name) {
    if (name === "@/i18n") return { useI18n: () => ({ locale: "en" }), translate: (source, params = {}) => source.replace(/\{(\w+)\}/g, (match, key) => String(params[key] ?? match)) };
    if (name === "react") return React;
    if (name === "react-native") return { View: "View" };
    if (name === "@/lib/accountDrafts") return { writeAccountDraft: (...args) => context.require("@react-native-async-storage/async-storage").setItem(...args) };
    if (name === "@react-native-async-storage/async-storage") return { getItem: async key => storage.get(key), setItem: async (key, value) => storage.set(key, value), removeItem: async key => storage.delete(key) };
    if (name === "@/api/client") return { req: async (path, init) => {
      if (path === "/v1/account") return { email: "merchant@example.com" };
      if (path.endsWith("ai-consent")) return { granted: true };
      if (!init) return { version: 7, resultVersion: "reviewed", state: "awaiting_user_decision" };
      assert.equal(storage.size, 1); sent.push(init);
      if (lost) throw Error("Lost response");
      return { state: "delivered" };
    } };
    return { Button: "Button", Text: "Text" };
  } };
  vm.runInNewContext(code, context);
  const render = (complete = true) => { slot = 0; return context.exports.CampaignDecision({ jobId: "job", resultVersion: "reviewed", price: 3, complete, onResolved: () => resolved++ }); };
  const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
  const button = label => nodes(render()).find(node => node.props?.label === label);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  render(); await settle();
  assert.equal(nodes(render(false)).find(node => node.props?.label === "Accept pack · 3 credits").props.disabled, true);
  button({ accept: "Accept pack · 3 credits", abort: "Cancel and release credits", spend_more: "Try again · 3 credits" }[action]).props.onPress(); await settle();
  assert.equal(sent.length, 1); assert.equal(resolved, 0);
  assert.deepEqual(JSON.parse(sent[0].body), { action, expectedVersion: 7, ...(action === "spend_more" ? { confirmedCredits: 3 } : {}) });
  state.length = 0; mounted = false; lost = false;
  render(); await settle();
  button(`Retry saved decision: ${{ accept: "Accept", abort: "Cancel", spend_more: "Try again" }[action]}`).props.onPress(); await settle();
  assert.equal(sent[0].headers["Idempotency-Key"], sent[1].headers["Idempotency-Key"]);
  assert.equal(sent[0].body, sent[1].body);
  assert.equal(resolved, 1); assert.equal(storage.size, 0);
}
console.log("Pack decisions preserve action/version/price and replay exact saved commands after restart");
