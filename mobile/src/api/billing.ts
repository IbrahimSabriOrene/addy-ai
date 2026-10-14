import { req, USE_MOCK } from "./client";

export type CreditPack = { productId: string; credits: number };
export type CreditPurchase = { id: string; productId: string; credits: number;
  status: "granted" | "reversed"; createdAt: string };

export async function getCreditPacks(): Promise<CreditPack[]> {
  if (USE_MOCK) return [];
  return (await req<{ items: CreditPack[] }>("/v1/credits/packs")).items;
}

export async function getCreditPurchases(): Promise<CreditPurchase[]> {
  if (USE_MOCK) return [];
  return (await req<{ items: CreditPurchase[] }>("/v1/credits/purchases")).items;
}

export function getCreditPurchaseStatus(transactionId: string, productId: string, store: string): Promise<{ status: "pending" | "granted" | "reversed"; credits?: number }> {
  const query = new URLSearchParams({ transactionId, productId, store });
  return req(`/v1/credits/purchases/status?${query}`);
}
