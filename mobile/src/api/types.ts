/**
 * Client-side types for the Python API. See release/API_CONTRACT_INVENTORY.md
 * and the server handlers; the backend owns job lifecycle and credit balances.
 */

export type PlatformKey = "tiktok" | "reels" | "feed" | "stories";

export type PresetId = "pedestal_spin" | "lifestyle_zoom" | "feature_pop" | "unboxing_pan";

export type JobState =
  | "submitted"
  | "running"
  | "validating"
  | "cleaning"
  | "planning"
  | "awaiting_style_choice"
  | "generating"
  | "composing"
  | "reviewing"
  | "delivering"
  | "delivered"
  | "needs_reshoot"
  | "awaiting_user_decision"
  | "aborted"
  | "failed";

export type StyleCandidate = {
  id: PresetId;
  name: string;
  oneLiner: string;
  captionPreview: string;
  motionRef?: string; // thumbnail/preview url (null in mock)
};

export type PlatformExport = {
  mimeType?: "image/png" | "image/jpeg" | "image/webp" | "video/mp4" | "video/webm";
  platform: PlatformKey;
  url: string;
  caption: string;
};

export type Job = {
  id: string;
  campaignId?: string | null;
  campaignVersion?: number | null;
  version?: number;
  gate?: "awaiting_style_choice" | "awaiting_user_decision" | null;
  title: string; // e.g. "Ceramic mug — spin"
  state: JobState;
  stage?: "planning" | "input_review" | "generating" | "generated" | "composed" | "reviewed" | null;
  progress?: number; // 0..100 while generating
  createdAt: string; // ISO
  sourceImage?: string;
  candidates?: StyleCandidate[];
  chosenPreset?: PresetId;
  platforms: PlatformKey[];
  exports?: PlatformExport[];
  resultVersion?: string;
  failure?: { code: "submission_unknown" | "generation_closed" | "incompatible_run" | "campaign_pack_incomplete" | "media_review_pending"; message: string } | null;
  outputKind?: "video" | "photo";
  /** For the budget-decision gate. */
  bestAttempt?: { attempt: number; url: string };
  videoGenAttempts?: number;
};

/** Durable command receipt; fetch GET job for its current full projection. */
export type JobCommandResult = Pick<Job, "id" | "state" | "platforms"> & Partial<Job>;

export type CreditsWallet = {
  balance: number;
  held?: number;
  pack: "starter" | "creator" | "pro" | null;
  packUsed?: number;
  packSize?: number;
};

export type CreditPack = {
  id: "starter" | "creator" | "pro";
  name: string;
  price: string;
  videos: number;
  perVideo?: string;
  badge?: "MOST POPULAR" | "BEST VALUE";
  productId: string; // App Store / RevenueCat product identifier
};

export type Account = {
  name: string;
  email: string;
  initial: string;
};

export type PresignedUpload = {
  expiresAt: string;
  uploadUrl: string;
  assetKey: string;
  method: "PUT";
  headers: Record<string, string>;
};
