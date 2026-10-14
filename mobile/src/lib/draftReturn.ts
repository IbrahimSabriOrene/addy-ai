import type { Href } from "expo-router";

export function draftReturn(value: unknown): Href | null {
  if (typeof value !== "string" || !value.startsWith("/create/") || value.length > 1000) return null;
  try {
    const url = new URL(value, "https://local.invalid");
    if (url.origin !== "https://local.invalid") return null;
    if (url.pathname === "/create/generating") {
      const id = url.searchParams.get("id");
      return id && id.length <= 200 ? { pathname: "/create/generating", params: { id } } : null;
    }
    const template = url.searchParams.get("template");
    if (!template || template.length > 200) return null;
    if (url.pathname === "/create/campaign") {
      const product = url.searchParams.get("product");
      return product && product.length <= 200 ? { pathname: "/create/campaign", params: { product, template } } : null;
    }
    const mode = url.searchParams.get("mode");
    return url.pathname === "/create/customize" && (mode === "photo" || mode === "video")
      ? { pathname: "/create/customize", params: { template, mode } } : null;
  } catch { return null; }
}
