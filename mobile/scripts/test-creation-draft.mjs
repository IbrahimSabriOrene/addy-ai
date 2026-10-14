import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../app/create/customize.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;
const storage = new Map(), commands = [];
let failNetwork = true, failStorage = false;
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };

async function mount(email = "first@example.com") {
  const hooks = [], routes = [];
  let cursor = 0, mounted = false;
  const React = {
    createElement: (type, props, ...children) => ({ type, props, children }),
    useState(initial) { const key = cursor++; if (!mounted) hooks[key] = initial; return [hooks[key], next => { hooks[key] = next; }]; },
    useRef(initial) { const key = cursor++; if (!mounted) hooks[key] = { current: initial }; return hooks[key]; },
    useEffect(effect) { if (!mounted) effect(); },
  };
  const context = { exports: {}, URLSearchParams, process: { env: { EXPO_PUBLIC_API_URL: "https://api.example" } }, require(name) {
  if (name === "@/i18n") { const tr = (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])); return { useI18n: () => ({ locale: "en", tr }), translate: tr }; }
    if (name === "react") return React;
    if (name === "expo-router") return { useRouter: () => ({ push: route => routes.push(route) }), useLocalSearchParams: () => ({ template: "pedestal_spin", mode: "photo" }) };
    if (name === "react-native") return { Platform: { OS: "web" }, View: "View", TextInput: "TextInput", ScrollView: "ScrollView", KeyboardAvoidingView: "KeyboardAvoidingView" };
    if (name === "react-native-safe-area-context") return { useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) };
    if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
    if (name === "@tanstack/react-query") return {
      useQuery: () => ({ data: { items: [{ id: "pedestal_spin", version: 1, name: "Pedestal spin", outputKinds: ["photo", "video"] }], executionMode: "fixture", generationEnabled: true, prices: { photo: 1, video: 1 } } }),
      useInfiniteQuery: () => ({ data: { pages: [{ items: [{ id: "product-1", assetKey: "original", name: "Mug" }] }] } }),
      useQueryClient: () => ({ invalidateQueries() {} }),
    };
    if (name === "@/lib/accountDrafts") return { writeAccountDraft: (...args) => context.require("@react-native-async-storage/async-storage").setItem(...args) };
    if (name === "@react-native-async-storage/async-storage") return {
      getItem: async key => storage.get(key) ?? null,
      setItem: async (key, value) => { if (failStorage) throw Error("Storage unavailable"); storage.set(key, value); },
    };
    if (name === "@/api/client") return { USE_MOCK: false, req: async path => {
      if (path === "/v1/account") return { email };
      if (path.endsWith("/approved-image")) return { image: { assetKey: "approved-image" } };
      throw Error(`Unexpected ${path}`);
    } };
    if (name === "@/api/creation") return { templatePreview: () => null, createFromDraft: async command => {
      const persisted = [...storage.values()].map(JSON.parse).find(draft => draft.command?.key === command.key);
      assert.ok(persisted, "Command must be durable before sending");
      commands.push(JSON.parse(JSON.stringify(command)));
      if (failNetwork) throw Error("Response lost");
      return { id: "job-1" };
    } };
    return new Proxy({}, { get: (_, key) => String(key) });
  } };
  vm.runInNewContext(compiled, context);
  function render() { cursor = 0; const result = context.exports.default(); mounted = true; return result; }
  function find(predicate, node) {
    if (!node || typeof node !== "object") return undefined;
    if (predicate(node)) return node;
    for (const child of Array.isArray(node) ? node : node.children ?? []) { const match = find(predicate, child); if (match) return match; }
  }
  render(); await settle();
  return { routes, render, find: predicate => find(predicate, render()), press: async label => { const button = find(node => node.props?.label === label, render()); assert.ok(button, label); assert.ok(!button.props.disabled, `${label} disabled`); button.props.onPress(); await settle(); } };
}

const first = await mount();
await first.press("Choose saved product");
await first.press("Use Mug");
await first.press("Generate · 1 credits");
assert.equal(commands.length, 1);
assert.equal(commands[0].body.assetKey, "approved-image");
assert.equal(commands[0].body.outputKind, "photo");
assert.deepEqual(commands[0].body.platforms, ["feed"]);
assert.equal(commands[0].body.direction, "", "Prompt remains optional");
assert.equal(first.routes.length, 0);

failNetwork = false;
const restarted = await mount();
await restarted.press("Retry same generation");
assert.deepEqual(commands[1], commands[0], "Restart must resend the identical command and idempotency key");
assert.deepEqual(restarted.routes, ["/create/generating?id=job-1"]);

const other = await mount("second@example.com");
assert.ok(other.find(node => node.props?.label === "Generate · 1 credits").props.disabled, "Other accounts must not inherit the product or command");
await other.press("Choose saved product");
await other.press("Use Mug");
failStorage = true;
await other.press("Generate · 1 credits");
assert.equal(commands.length, 2, "Storage failure must prevent submission");
console.log("Creation: approved image reuse, photo routing, optional prompt, durable replay and account isolation verified");
