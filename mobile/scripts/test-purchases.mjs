import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../src/lib/purchases.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
let session = { user: { id: "account-a" } }, identity, configured = false;
let purchases = 0, restores = 0, lookups = 0, fetchProducts, checkout;
const storage = new Map();
let backendStatus = "pending", storageFailure = false;
const product = { identifier: "credits", title: "10 credits", priceString: "₺99,99" };
const sdk = {
  PRODUCT_CATEGORY: { NON_SUBSCRIPTION: "NON_SUBSCRIPTION" },
  isConfigured: async () => configured,
  configure: options => { configured = true; identity = options.appUserID; },
  getAppUserID: async () => identity,
  logIn: async id => { identity = id; },
  getProducts: async (ids, category) => {
    assert.equal(category, "NON_SUBSCRIPTION"); lookups++;
    return fetchProducts ? fetchProducts() : [product];
  },
  purchaseStoreProduct: async item => { assert.equal(item, product); purchases++; if (checkout) await checkout();
    return { transaction: { productIdentifier: "credits", transactionIdentifier: `store-${purchases}` } }; },
  restorePurchases: async () => { restores++; },
};
function load(key = "fixture", platform = "ios", apiUrl = "https://fixture.invalid") {
  const context = { exports: {}, process: { env: { EXPO_PUBLIC_REVENUECAT_KEY: key, EXPO_PUBLIC_API_URL: apiUrl } }, require(name) {
    if (name === "react-native") return { Platform: { OS: platform } };
    if (name === "./supabase") return { supabase: { auth: { getSession: async () => ({ data: { session } }) } } };
    if (name === "react-native-purchases") return { __esModule: true, default: sdk };
    if (name === "@react-native-async-storage/async-storage") return { __esModule: true, default: {
      getItem: async key => storage.get(key) ?? null,
      setItem: async (key, value) => { if (storageFailure) throw Error("Disk unavailable"); storage.set(key, value); },
      removeItem: async key => storage.delete(key),
    } };
    if (name === "../api/billing") return { getCreditPurchaseStatus: async () => {
      if (backendStatus === "offline") throw Error("Offline"); return { status: backendStatus };
    } };
    throw Error(name);
  } };
  vm.runInNewContext(source, context);
  return context.exports;
}
for (const api of [load(""), load("fixture", "web"), load("fixture", "ios", "")]) {
  await assert.rejects(api.purchasePack("credits"), /unavailable/);
  await assert.rejects(api.restorePurchases(), /unavailable/);
}
assert.equal(purchases + restores + lookups, 0);
const api = load();
assert.equal((await api.getCreditProducts(["credits"]))[0].priceString, "₺99,99");
assert.equal(identity, "account-a");
session = { user: { id: "account-b" } };
await api.purchasePack("credits");
assert.equal(identity, "account-b");
assert.equal(purchases, 1);
assert.equal((await load().readPendingPurchase()).transactionId, "store-1", "Restart retains returned store transaction");
await assert.rejects(load().purchasePack("credits"), /awaiting confirmation/);
assert.ok(await api.checkPendingPurchase(), "No ledger confirmation yet");
backendStatus = "offline";
await assert.rejects(api.checkPendingPurchase(), /Offline/);
assert.ok(await api.readPendingPurchase(), "Network errors retain pending checkout");
backendStatus = "granted";
assert.equal(await api.checkPendingPurchase(), null);
backendStatus = "pending";
await load().restorePurchases(); // App restart with SDK already configured.
assert.equal(restores, 1);
session = null;
await assert.rejects(api.purchasePack("credits"), /Sign in/);
session = { user: { id: "account-b" } };
fetchProducts = async () => { session = { user: { id: "account-c" } }; return [product]; };
await assert.rejects(api.purchasePack("credits"), /account changed/);
assert.equal(purchases, 1);
fetchProducts = async () => [];
await assert.rejects(api.purchasePack("credits"), /unavailable/);
fetchProducts = undefined;
const cancelled = Object.assign(Error("Cancelled"), { userCancelled: true });
checkout = async () => { throw cancelled; };
await assert.rejects(api.purchasePack("credits"), error => error === cancelled);
let release, entered;
const opened = new Promise(resolve => { entered = resolve; });
checkout = () => { entered(); return new Promise(resolve => { release = resolve; }); };
const pending = api.purchasePack("credits");
await opened;
await assert.rejects(api.purchasePack("credits"), /already in progress/);
await assert.rejects(api.restorePurchases(), /already in progress/);
release(); await pending;
checkout = undefined;
await api.restorePurchases();
assert.equal(restores, 2, "Operation lock is released after cancellation and completion");
assert.ok(await api.readPendingPurchase());
session = { user: { id: "account-d" } };
assert.equal(await api.readPendingPurchase(), null, "Pending checkout is private to its account");
session = { user: { id: "account-c" } };
assert.equal(await load("fixture", "ios", "https://other.invalid").readPendingPurchase(), null);
await api.acknowledgePendingPurchase();
storageFailure = true;
const before = purchases;
await assert.rejects(api.purchasePack("credits"), /Disk unavailable/);
assert.equal(purchases, before, "Durable write must succeed before opening store checkout");
storageFailure = false;
checkout = async () => { throw Error("Checkout connection lost"); };
await assert.rejects(api.purchasePack("credits"), /connection lost/);
assert.equal((await load().readPendingPurchase()).transactionId, undefined);
await assert.rejects(api.purchasePack("credits"), /awaiting confirmation/);
await api.acknowledgePendingPurchase();
assert.equal(await api.readPendingPurchase(), null);
checkout = async () => { storageFailure = true; };
await assert.rejects(api.purchasePack("credits"), /Disk unavailable/);
storageFailure = false;
assert.equal((await load().readPendingPurchase()).transactionId, undefined, "Post-checkout disk failure retains pre-checkout marker");
await assert.rejects(api.purchasePack("credits"), /awaiting confirmation/);
console.log("Purchase boundaries passed: unavailable builds, identity switch/restart, store prices, consumables, cancellation and concurrent operations.");
