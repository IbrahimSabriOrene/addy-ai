import { Platform } from "react-native";
import { req, USE_MOCK } from "./client";
import { Asset } from "expo-asset";

export type OutputKind = "video" | "photo";
export type Template = { id: string; version: number; name: string; presentation?: string; categories: string[]; outputKinds: OutputKind[]; preview: string | null; poster?: string; previews?: Partial<Record<OutputKind, string>> };
export type Catalogue = { categories: { id: string; name: string }[]; items: Template[]; generationEnabled: boolean;
  modes?: Partial<Record<OutputKind, { generationEnabled: boolean; executionMode: "fixture" | "google"; requiresAiConsent: boolean }>>;
  formats?: Record<OutputKind, string>; supportedPlatforms?: string[];
  executionMode: "fixture" | "google"; requiresAiConsent?: boolean; prices: Record<OutputKind, number> };
export type Product = { id: string; name: string; assetKey: string };
export type CreationCommand = { key: string; body: { assetKey: string; platforms: string[]; fastMode: boolean;
  quality: "fast"; templateId: string; templateVersion: number; outputKind: OutputKind; direction: string } };
export type CreationDraft = { assetKey: string; productName: string; direction: string; command?: CreationCommand; jobId?: string };

export function templatePreview(template: Template | undefined, mode: OutputKind): string | null {
  return template?.previews?.[mode] ?? (template?.outputKinds.length === 1 ? template.preview : null);
}

export async function getCatalogue(): Promise<Catalogue> {
  if (!USE_MOCK) return req("/v1/catalogue");
  return { categories: [{"id": "beauty", "name": "Beauty & Skincare"}, {"id": "jewelry", "name": "Jewelry"}, {"id": "food", "name": "Food & Drinks"}, {"id": "fashion", "name": "Fashion & Bags"}, {"id": "home", "name": "Home & Decor"}, {"id": "gifts", "name": "Gifts & Handmade"}, {"id": "tech", "name": "Tech & Gadgets"}, {"id": "pets", "name": "Pet Accessories"}],
    items: [
      { id: "skincare_glow", name: "Studio glow", category: "beauty", presentation: "Studio orbit", photo: require("../../public/previews/skincare_glow.photo.jpg"), poster: require("../../public/previews/skincare_glow.poster.jpg"), video: require("../../public/previews/skincare_glow.preview.mp4") },
      { id: "jewelry_detail", name: "Fine details", category: "jewelry", presentation: "Detail slide", photo: require("../../public/previews/jewelry_detail.photo.jpg"), poster: require("../../public/previews/jewelry_detail.poster.jpg"), video: require("../../public/previews/jewelry_detail.preview.mp4") },
      { id: "bakery_morning", name: "Freshly baked", category: "food", presentation: "Lifestyle", photo: require("../../public/previews/bakery_morning.photo.jpg"), poster: require("../../public/previews/bakery_morning.poster.jpg"), video: require("../../public/previews/bakery_morning.preview.mp4") },
      { id: "pedestal_spin", name: "Pedestal spin", category: "home", presentation: "Studio orbit", photo: require("../../public/previews/pedestal_spin.photo.jpg"), poster: require("../../public/previews/pedestal_spin.poster.jpg"), video: require("../../public/previews/pedestal_spin.preview.mp4") },
      { id: "coffee_ritual", name: "Coffee ritual", category: "food", presentation: "Lifestyle", photo: require("../../public/previews/coffee_ritual.photo.jpg"), poster: require("../../public/previews/coffee_ritual.poster.jpg"), video: require("../../public/previews/coffee_ritual.preview.mp4") },
      { id: "leather_editorial", name: "Leather editorial", category: "fashion", presentation: "Detail slide", photo: require("../../public/previews/leather_editorial.photo.jpg"), poster: require("../../public/previews/leather_editorial.poster.jpg"), video: require("../../public/previews/leather_editorial.preview.mp4") },
      { id: "candle_dusk", name: "After dusk", category: "home", presentation: "Atmosphere", photo: require("../../public/previews/candle_dusk.photo.jpg"), poster: require("../../public/previews/candle_dusk.poster.jpg"), video: require("../../public/previews/candle_dusk.preview.mp4") },
      { id: "gift_unwrap", name: "Gift reveal", category: "gifts", presentation: "Flat lay", photo: require("../../public/previews/gift_unwrap.photo.jpg"), poster: require("../../public/previews/gift_unwrap.poster.jpg"), video: require("../../public/previews/gift_unwrap.preview.mp4") },
      { id: "tech_light", name: "Light reveal", category: "tech", presentation: "Light sweep", photo: require("../../public/previews/tech_light.photo.jpg"), poster: require("../../public/previews/tech_light.poster.jpg"), video: require("../../public/previews/tech_light.preview.mp4") },
      { id: "pet_boutique", name: "Everyday essentials", category: "pets", presentation: "Detail slide", photo: require("../../public/previews/pet_boutique.photo.jpg"), poster: require("../../public/previews/pet_boutique.poster.jpg"), video: null },
    ].map(item => ({ id: item.id, version: 1, name: item.name, presentation: item.presentation, categories: [item.category], outputKinds: (item.video ? ["video", "photo"] : ["photo"]) as OutputKind[], preview: null, poster: Platform.OS === "web" ? `/previews/${item.id}.poster.jpg` : Asset.fromModule(item.poster).uri,
      previews: { photo: Platform.OS === "web" ? `/previews/${item.id}.photo.jpg` : Asset.fromModule(item.photo).uri, ...(item.video ? { video: Platform.OS === "web" ? `/previews/${item.id}.preview.mp4` : Asset.fromModule(item.video).uri } : {}) } })),
    generationEnabled: false, executionMode: "fixture", prices: { photo: 1, video: 1 } };
}

export function createFromDraft(command: CreationCommand): Promise<{ id: string }> {
  return req("/v1/jobs", { method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body) });
}
