/**
 * Mock data + a fake in-memory backend so the app runs end-to-end with zero
 * network — the same discipline as the Python worker fakes. Swap `USE_MOCK`
 * off (client.ts) once the Python account service is connected.
 */
import { Asset } from "expo-asset";
import { Platform } from "react-native";
import type { Account, CreditPack, CreditsWallet, Job, StyleCandidate } from "./types";

export const MOCK_SAMPLE_VIDEO_URL = "/mock/sample-ad.mp4";

export const MOCK_SAMPLE_PROMPT = {
  product: "hand-thrown ceramic mug with teal glaze",
  preset: "pedestal_spin",
  prompt:
    "Create a premium 9:16 product ad for a small-batch ceramic mug on a black studio background. Open with a bold NEW DROP title, reveal the mug on a glowing teal pedestal, add a slow 360-style hero motion, soft rim lighting, subtle gold sparkle accents, and finish with a clean Shop the drop CTA.",
};

export const MOCK_ACCOUNT: Account = {
  name: "Maya's Ceramics",
  email: "maya@example.test",
  initial: "M",
};

export const MOCK_WALLET: CreditsWallet = {
  balance: 3,
  pack: "creator",
  packUsed: 11,
  packSize: 14,
};

export const CREDIT_PACKS: CreditPack[] = [
  { id: "starter", name: "Starter", price: "$4.99", videos: 3, productId: "mam.credits.starter" },
  {
    id: "creator",
    name: "Creator",
    price: "$19.99",
    videos: 14,
    perVideo: "$1.43 each",
    badge: "MOST POPULAR",
    productId: "mam.credits.creator",
  },
  {
    id: "pro",
    name: "Pro",
    price: "$99.99",
    videos: 75,
    perVideo: "$1.33 each",
    badge: "BEST VALUE",
    productId: "mam.credits.pro",
  },
];

export const MOCK_CANDIDATES: StyleCandidate[] = [
  {
    id: "pedestal_spin",
    motionRef: Asset.fromModule(require("../../public/previews/pedestal_spin.png")).uri,
    name: "Pedestal spin",
    oneLiner: "Slow 360° turn on a lit podium.",
    captionPreview: "The glow-up your shelf has been waiting for ✦",
  },
  {
    id: "lifestyle_zoom",
    motionRef: Asset.fromModule(require("../../public/previews/lifestyle_zoom.png")).uri,
    name: "Lifestyle zoom",
    oneLiner: "Push-in on the product in a real scene.",
    captionPreview: "Meet the little upgrade you'll use every day.",
  },
  {
    id: "feature_pop",
    motionRef: Asset.fromModule(require("../../public/previews/feature_pop.png")).uri,
    name: "Feature pop",
    oneLiner: "Punchy cuts with callout labels.",
    captionPreview: "3 reasons this sells out every week →",
  },
];

export const MOCK_CREATION_MEDIA = {
  job_1: { title: "Ceramic mug", preset: "pedestal_spin", photo: require("../../public/previews/pedestal_spin.png"), video: require("../../public/previews/pedestal_spin.mp4"), caption: "Made for slow mornings. Discover our ceramic collection. #ceramics #smallbusiness" },
  job_2: { title: "Skincare serum", preset: "skincare_glow", photo: require("../../public/previews/skincare_glow.png"), video: require("../../public/previews/skincare_glow.mp4"), caption: "A little moment for your daily routine. Explore the collection. #skincare #smallbusiness" },
  job_3: { title: "Fresh croissants", preset: "bakery_morning", photo: require("../../public/previews/bakery_morning.png"), video: require("../../public/previews/bakery_morning.mp4"), caption: "Make time for a bakery morning. Visit us for your next treat. #bakery #shoplocal" },
  job_4: { title: "Handmade earrings", preset: "jewelry_detail", photo: require("../../public/previews/jewelry_detail.png"), video: require("../../public/previews/jewelry_detail.mp4"), caption: "Small details, personal style. Explore our earrings. #jewelry #smallbusiness" },
};

export const MOCK_LIBRARY: Job[] = Object.entries(MOCK_CREATION_MEDIA).map(([id, media], index) => ({
  id, title: media.title, state: "delivered", version: 1,
  createdAt: new Date(Date.now() - (index + 1) * 3600e3).toISOString(),
  platforms: ["tiktok", "reels"],
  exports: (["tiktok", "reels"] as const).map(platform => ({
    platform, caption: media.caption,
    url: Platform.OS === "web" ? `/previews/${media.preset}.mp4` : Asset.fromModule(media.video).uri,
  })),
}));

export const MOCK_RESULT: Job = {
  id: "job_new",
  title: "Ceramic mug — spin",
  state: "delivered",
  createdAt: new Date().toISOString(),
  platforms: ["tiktok", "reels", "feed", "stories"],
  chosenPreset: "pedestal_spin",
  bestAttempt: { attempt: 2, url: MOCK_SAMPLE_VIDEO_URL },
  videoGenAttempts: 2,
  exports: [
    {
      platform: "tiktok",
      url: MOCK_SAMPLE_VIDEO_URL,
      caption: "The glaze your morning shelf has been waiting for. Shop the kiln-fresh drop before it sells out. #smallbusiness #ceramics #newdrop",
    },
    { platform: "reels", url: MOCK_SAMPLE_VIDEO_URL, caption: "A fresh teal glaze, made for slow mornings. #ceramics #smallbusiness" },
    { platform: "feed", url: MOCK_SAMPLE_VIDEO_URL, caption: "Small-batch ceramic mugs, kiln-fresh and ready for your shelf." },
    { platform: "stories", url: MOCK_SAMPLE_VIDEO_URL, caption: "Shop the kiln-fresh drop before it sells out." },
  ],
};
