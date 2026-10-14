import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../app/paywall.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;
let state = [], index = 0, mounted = false, effects = [], credits = 17, purchases = 0, requested;
let pendingPurchase = null;
let restore = async () => {};
const React = {
  createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }),
  useState: initial => { const slot = index++; if (!(slot in state)) state[slot] = initial; return [state[slot], value => { state[slot] = value; }]; },
  useEffect: effect => { if (!mounted) effects.push(effect); },
};
const wallet = { data: { balance: 9 }, refetch: async () => {}, isError: false };
const context = { exports: {}, require(name) {
  if (name === "@/i18n") return { useI18n: () => ({ locale: "en", tr: (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])) }) };
  if (name === "@/api/client") return { USE_MOCK: false };
  if (name === "react") return React;
  if (name === "react-native") return { View: "View", Pressable: "Pressable" };
  if (name === "expo-router") return { useRouter: () => ({ back() {} }), useLocalSearchParams: () => ({}) };
  if (name === "@/lib/draftReturn") return { draftReturn: () => null };
  if (name === "@/lib/publicLinks") return { TERMS_URL: "https://example.test/terms", openPublicLink: async () => {} };
  if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {}, radius: {}, fonts: {} }) };
  if (name === "@/api/hooks") return { useWallet: () => wallet };
  if (name === "@/api/billing") return {
    getCreditPacks: async () => [{ productId: "server-only-pack", credits }],
    getCreditPurchases: async () => [{ id: "confirmed", productId: "server-only-pack", credits: 17, status: "granted", createdAt: "2026-09-08T00:00:00Z" }],
  };
  if (name === "@/lib/purchases") return {
    readPendingPurchase: async () => pendingPurchase,
    checkPendingPurchase: async () => pendingPurchase,
    acknowledgePendingPurchase: async () => { pendingPurchase = null; },
    IAP_CONFIGURED: true,
    getCreditProducts: async ids => { requested = ids; return [{ identifier: "server-only-pack", priceString: "€2,39", title: "Store pack" }]; },
    purchasePack: async id => { assert.equal(id, "server-only-pack"); purchases++; },
    restorePurchases: () => restore(),
  };
  if (name.startsWith("@/components/")) {
    const symbol = name.split("/").at(-1);
    return symbol === "Icons" ? { Apple: "Apple" } : { [symbol]: symbol };
  }
  throw Error(name);
} };
vm.runInNewContext(source, context);
function render() { index = 0; const tree = context.exports.default(); mounted = true; return tree; }
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...tree.children.flatMap(nodes)];
}
function text(tree) { return JSON.stringify(tree); }
render(); effects.forEach(effect => effect());
await new Promise(resolve => setImmediate(resolve));
let tree = render();
assert.deepEqual(Array.from(requested), ["server-only-pack"], "Product IDs come from the backend, not mock packs");
let buy = nodes(tree).find(node => node.type === "Button" && node.props.label.startsWith("Buy "));
assert.equal(buy.props.label, "Buy 17 credits — €2,39");
assert.match(text(tree), /Granted/);
await buy.props.onPress();
assert.equal(purchases, 1);
assert.match(text(render()), /Credits appear after server confirmation/);
credits = 29;
tree = render();
buy = nodes(tree).find(node => node.type === "Button" && node.props.label.startsWith("Buy "));
await buy.props.onPress();
assert.equal(purchases, 1, "Changed server credits block checkout until redisplayed");
assert.match(text(render()), /Credit packs changed/);
wallet.isError = true;
assert.match(text(render()), /unavailable/);
pendingPurchase = { productId: "server-only-pack", startedAt: "2026-09-08T00:00:00Z" };
state = []; index = 0; mounted = false; effects = []; credits = 17;
render(); effects.forEach(effect => effect());
await new Promise(resolve => setImmediate(resolve));
tree = render();
buy = nodes(tree).find(node => node.type === "Button" && node.props.label.startsWith("Buy "));
assert.equal(buy.props.disabled, true, "Reopened paywall blocks another checkout");
assert.match(text(tree), /awaiting confirmation/);
await nodes(tree).find(node => node.props.label === "Review unresolved purchase").props.onPress();
assert.match(text(render()), /second charge/);
await nodes(render()).find(node => node.props.label === "I checked; allow another purchase").props.onPress();
assert.equal(pendingPurchase, null);
assert.equal(nodes(render()).find(node => node.type === "Button" && node.props.label.startsWith("Buy ")).props.disabled, false);
let rejectRestore;
restore = () => new Promise((_, reject) => { rejectRestore = reject; });
const restoreButton = () => nodes(render()).find(node => node.props.accessibilityLabel === "Restore purchases");
assert.equal(restoreButton().props.accessibilityState.disabled, false);
const restoring = restoreButton().props.onPress();
assert.equal(restoreButton().props.accessibilityState.busy, true);
assert.equal(restoreButton().props.accessibilityState.disabled, true);
rejectRestore(new Error("Restore offline"));
await restoring;
assert.match(text(render()), /Restore could not be confirmed/);
assert.equal(restoreButton().props.accessibilityState.busy, false);
assert.equal(restoreButton().props.accessibilityState.disabled, false);
console.log("Paywall passed: authoritative packs, pending purchase guards and restore busy/disabled recovery after failure.");
