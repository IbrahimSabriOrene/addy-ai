import { Platform } from "react-native";
import { supabase } from "./supabase";
import type { PurchasesStoreProduct } from "react-native-purchases";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { getCreditPurchaseStatus } from "../api/billing";

const RC_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_KEY ?? "";
export const IAP_CONFIGURED = !!RC_API_KEY && !!process.env.EXPO_PUBLIC_API_URL && Platform.OS !== "web";
let operationPending = false;

export type PendingPurchase = { productId: string; startedAt: string; store: "APP_STORE" | "PLAY_STORE"; transactionId?: string };

async function pendingKey(): Promise<string> {
  const session = (await supabase?.auth.getSession())?.data.session;
  if (!session?.user.id) throw new Error("Sign in to check pending purchases.");
  return `pending-purchase:${process.env.EXPO_PUBLIC_API_URL}:${session.user.id}`;
}

export async function readPendingPurchase(): Promise<PendingPurchase | null> {
  const value = await AsyncStorage.getItem(await pendingKey());
  if (!value) return null;
  const pending = JSON.parse(value);
  if (!pending || typeof pending.productId !== "string" || typeof pending.startedAt !== "string"
    || !["APP_STORE", "PLAY_STORE"].includes(pending.store)
    || (pending.transactionId !== undefined && typeof pending.transactionId !== "string")) {
    throw new Error("Saved purchase needs review before another checkout.");
  }
  return pending;
}

export async function checkPendingPurchase(): Promise<PendingPurchase | null> {
  if (operationPending) return readPendingPurchase();
  operationPending = true;
  try {
    const key = await pendingKey();
    const pending = await readPendingPurchase();
    if (pending?.transactionId) {
      const result = await getCreditPurchaseStatus(pending.transactionId, pending.productId, pending.store);
      if ((result.status === "granted" || result.status === "reversed") && key === await pendingKey()) {
        await AsyncStorage.removeItem(key);
        return null;
      }
    }
    return pending;
  } finally { operationPending = false; }
}

/** Explicit user acknowledgement only; this does not cancel or refund a store charge. */
export async function acknowledgePendingPurchase(): Promise<void> {
  if (operationPending) throw new Error("A store operation is already in progress.");
  await AsyncStorage.removeItem(await pendingKey());
}

/** Bind billing to the current authenticated account, including after app restart. */
export async function configurePurchases(): Promise<void> {
  if (!IAP_CONFIGURED) throw new Error("Purchases are unavailable in this build.");
  const session = (await supabase?.auth.getSession())?.data.session;
  if (!session?.user.id) throw new Error("Sign in before purchasing or restoring credits.");
  const Purchases = require("react-native-purchases").default;
  if (!(await Purchases.isConfigured())) {
    Purchases.configure({ apiKey: RC_API_KEY, appUserID: session.user.id });
  } else if (await Purchases.getAppUserID() !== session.user.id) {
    await Purchases.logIn(session.user.id);
  }
}

// Serialize identity changes with the store sheet; never queue another purchase.
async function withPurchases<T>(action: (sdk: typeof import("react-native-purchases").default) => Promise<T>): Promise<T> {
  if (operationPending) throw new Error("A store operation is already in progress.");
  operationPending = true;
  try {
    await configurePurchases();
    return await action(require("react-native-purchases").default);
  } finally {
    operationPending = false;
  }
}

export async function getCreditProducts(ids: string[]): Promise<PurchasesStoreProduct[]> {
  return withPurchases(sdk => sdk.getProducts(ids, sdk.PRODUCT_CATEGORY.NON_SUBSCRIPTION));
}

/** Store completion is not confirmation that the backend has granted credits. */
export async function purchasePack(productId: string): Promise<void> {
  await withPurchases(async sdk => {
    const key = await pendingKey();
    if (await readPendingPurchase()) throw new Error("A purchase is awaiting confirmation. Check it before buying again.");
    const products = await sdk.getProducts([productId], sdk.PRODUCT_CATEGORY.NON_SUBSCRIPTION);
    const product = products.find(item => item.identifier === productId);
    if (!product) throw new Error("This credit pack is unavailable in your store.");
    const session = (await supabase?.auth.getSession())?.data.session;
    if (!session || session.user.id !== await sdk.getAppUserID()) {
      throw new Error("Your account changed. Reopen the credit store.");
    }
    const pending: PendingPurchase = { productId, startedAt: new Date().toISOString(),
      store: Platform.OS === "ios" ? "APP_STORE" : "PLAY_STORE" };
    await AsyncStorage.setItem(key, JSON.stringify(pending));
    if (key !== await pendingKey()) {
      await AsyncStorage.removeItem(key);
      throw new Error("Your account changed. Reopen the credit store.");
    }
    try {
      const result = await sdk.purchaseStoreProduct(product);
      const transaction = result.transaction;
      if (transaction?.productIdentifier === productId && transaction.transactionIdentifier) {
        await AsyncStorage.setItem(key, JSON.stringify({ ...pending, transactionId: transaction.transactionIdentifier }));
      }
    } catch (error) {
      if ((error as { userCancelled?: boolean }).userCancelled) await AsyncStorage.removeItem(key);
      throw error;
    }
  });
}

export async function restorePurchases(): Promise<void> {
  await withPurchases(async sdk => { await sdk.restorePurchases(); });
}
