import {listLocalEdits} from "@/lib/localEdits";
/**
 * Typed client for the Python API. Every call is a
 * plain fetch against the REST API; the app holds no business logic.
 *
 * `USE_MOCK` short-circuits to the in-memory fakes so the whole app runs
 * offline during design/dev. Flip it off (or set EXPO_PUBLIC_API_URL) to hit
 * the real backend.
 */
import { createDemoJob, listDemoJobs } from "./demoJobs";
import * as FileSystem from "expo-file-system/legacy";
import { AppState, Platform } from "react-native";
import type {
  Account,
  CreditsWallet,
  Job,
  JobCommandResult,
  PlatformKey,
  PresetId,
  PresignedUpload,
} from "./types";
import {
  MOCK_ACCOUNT,
  MOCK_CANDIDATES,
  MOCK_LIBRARY,
  MOCK_RESULT,
  MOCK_WALLET,
} from "./mock";
import { getToken, refreshAccessToken, clearTokens } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

// Accept the documented `/v1` URL while keeping route construction uniform.
const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/v1\/?$/, "");
export const USE_MOCK = !API_URL;

// ---------------------------------------------------------------------------
// Error classes
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super("Network request failed — check your connection and try again.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

export class AuthError extends ApiError {
  constructor(message = "Session expired — please sign in again.") {
    super(401, "auth_required", message);
    this.name = "AuthError";
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      return refreshAccessToken();
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

/**
 * Core fetch wrapper — attaches auth, parses typed error bodies, and handles
 * 401 refresh transparently.
 */
export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
    ...((init?.headers as Record<string, string>) ?? {}),
  };

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch (err) {
    throw new NetworkError(err);
  }

  if (res.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retryHeaders = { ...headers, ...(await authHeaders()) };
      try {
        res = await fetch(`${API_URL}${path}`, { ...init, headers: retryHeaders });
      } catch (err) {
        throw new NetworkError(err);
      }
    }
    if (res.status === 401) {
      await clearTokens();
      throw new AuthError();
    }
  }

  if (!res.ok) {
    let code = "unknown";
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { code?: string; message?: string };
      if (body.code) code = body.code;
      if (body.message) message = body.message;
    } catch {
      // Response wasn't JSON — keep the status-line message.
    }
    throw new ApiError(res.status, code, message);
  }

  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Presigned upload
// ---------------------------------------------------------------------------

export async function uploadImage(localUri: string): Promise<string> {
  let blob: Blob | undefined;
  let sizeBytes: number;
  let mimeType: string;
  if (Platform.OS === "web") {
    const file = await fetch(localUri);
    if (!file.ok) throw new ApiError(422, "image_missing", "Image file is missing.");
    blob = await file.blob();
    sizeBytes = blob.size;
    mimeType = blob.type;
  } else {
    const info = await FileSystem.getInfoAsync(localUri);
    if (!info.exists || !("size" in info) || !info.size) throw new ApiError(422, "image_missing", "Image file is missing.");
    sizeBytes = info.size;
    const extension = localUri.split(/[?#]/)[0].split(".").pop()?.toLowerCase();
    mimeType = ({ jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" } as Record<string, string>)[extension ?? ""] ?? "";
  }
  if (!["image/jpeg", "image/png", "image/webp"].includes(mimeType) || !sizeBytes || sizeBytes > 10 * 1024 * 1024) {
    throw new ApiError(422, "unsupported_image", "Choose a JPEG, PNG or WebP image up to 10 MB.");
  }
  const { uploadUrl, assetKey, headers, method } = await req<PresignedUpload>(
    "/v1/uploads/presign",
    { method: "POST", body: JSON.stringify({ mimeType, sizeBytes }) },
  );
  const destination = new URL(uploadUrl, `${API_URL}/`);
  const uploadHeaders = { ...(destination.origin === new URL(API_URL).origin ? await authHeaders() : {}), ...headers };
  const upload = blob
    ? await fetch(destination.href, { method, headers: uploadHeaders, body: blob })
    : await FileSystem.uploadAsync(destination.href, localUri, {
        httpMethod: method, headers: uploadHeaders,
        uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
      });
  if (upload.status < 200 || upload.status >= 300) throw new ApiError(upload.status, "upload_failed", "Upload failed");
  await req("/v1/uploads/complete", { method: "POST", body: JSON.stringify({ assetKey }) });
  return assetKey;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const api = {
  async getAccount(): Promise<Account> {
    if (USE_MOCK) return MOCK_ACCOUNT;
    return req("/v1/account");
  },

  async getWallet(): Promise<CreditsWallet> {
    if (USE_MOCK) return MOCK_WALLET;
    return req("/v1/credits");
  },

  async listJobs(page = 1, limit = 20): Promise<Job[]> {
    return (await api.listJobPage(undefined, limit)).items;
  },

  async listJobPage(cursor?: string, limit = 20): Promise<{ items: Job[]; nextCursor: string | null }> {
    const email=USE_MOCK?"demo":(await req<{email:string}>("/v1/account")).email;
    const edits=cursor?[]:await listLocalEdits(email);
    if (USE_MOCK) return { items: [...edits,...await listDemoJobs(), ...MOCK_LIBRARY], nextCursor: null };
    const page=await req<{items:Job[];nextCursor:string|null}>(`/v1/jobs?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    return {...page,items:[...edits,...page.items]};
  },

  async getJob(id: string): Promise<Job> {
    if(id.startsWith("edit_")){
      const email=USE_MOCK?"demo":(await req<{email:string}>("/v1/account")).email;
      const edited=(await listLocalEdits(email)).find(item=>item.id===id);
      if(!edited)throw new ApiError(404,"edit_missing","Edited creation was not found on this device.");
      return edited;
    }
    if (USE_MOCK) {
      const job = [...await listDemoJobs(), ...MOCK_LIBRARY].find(j => j.id === id);
      if (!job && id.startsWith("demo_")) throw new ApiError(404, "job_missing", "Demo creation was not found on this device.");
      return { version: 1, ...(job ?? MOCK_RESULT) };
    }
    const job = await req<Job>(`/v1/jobs/${id}`);
    return {
      ...job,
      exports: job.exports?.map((item) => ({
        ...item,
        url: item.url.startsWith("http") ? item.url : `${API_URL}${item.url}`,
      })),
    };
  },

  /** Upload the product image, then create the job with the asset key. */
  async createJob(input: {
    imageUri: string;
    platforms: PlatformKey[];
    fastMode: boolean;
  }): Promise<JobCommandResult> {
    if (USE_MOCK) {
      return createDemoJob({ title: "Demo sample", outputKind: "video", platforms: input.platforms, exports: MOCK_RESULT.exports });
    }
    const assetKey = await uploadImage(input.imageUri);
    return req("/v1/jobs", {
      method: "POST",
      headers: { "Idempotency-Key": `job-${Date.now()}` },
      body: JSON.stringify({
        assetKey,
        platforms: input.platforms,
        fastMode: input.fastMode,
      }),
    });
  },

  /** Resume the awaiting_style_choice gate. */
  async chooseStyle(
    id: string,
    choice: PresetId | { direction: string },
    expectedVersion: number,
  ): Promise<JobCommandResult> {
    if (USE_MOCK) {
      await wait(300);
      return { ...MOCK_RESULT, id, state: "generating", progress: 0 };
    }
    return req(`/v1/jobs/${id}/style-choice`, {
      method: "POST",
      headers: { "Idempotency-Key": `style-${id}-${expectedVersion}` },
      body: JSON.stringify({ ...(typeof choice === "string" ? { presetId: choice } : choice), expectedVersion }),
    });
  },

  /** Resume the budget-decision gate. */
  async decide(
    id: string,
    action: "accept" | "spend_more" | "abort",
    expectedVersion: number,
    key?: string,
  ): Promise<JobCommandResult> {
    if (USE_MOCK) {
      await wait(300);
      return {
        ...MOCK_RESULT,
        id,
        state: action === "abort" ? "aborted" : "delivered",
      };
    }
    return req(`/v1/jobs/${id}/decision`, {
      method: "POST",
      headers: { "Idempotency-Key": key ?? `decision-${id}-${expectedVersion}` },
      body: JSON.stringify({ action, expectedVersion }),
    });
  },

  /** User-triggered regen (costs 1 credit, separate counter). */
  async regen(id: string, expectedVersion: number): Promise<JobCommandResult> {
    if (USE_MOCK) {
      return { ...MOCK_RESULT, id, state: "generating", progress: 0 };
    }
    return req(`/v1/jobs/${id}/regen`, { method: "POST", headers: { "Idempotency-Key": `regen-${id}-${expectedVersion}` }, body: JSON.stringify({ expectedVersion }) });
  },
};

// ---------------------------------------------------------------------------
// Poll with backoff, timeout, and abort support
// ---------------------------------------------------------------------------

const TERMINAL_STATES: Job["state"][] = [
  "delivered",
  "needs_reshoot",
  "awaiting_style_choice",
  "awaiting_user_decision",
  "aborted",
  "failed",
];

export interface PollOptions {
  /** Starting interval in ms (default 2 000). */
  intervalMs?: number;
  /** Max interval in ms after backoff (default 15 000). */
  maxIntervalMs?: number;
  /** Total wall-clock timeout in ms (default 600 000 = 10 min). */
  timeoutMs?: number;
  /** AbortSignal — cancel the poll from outside. */
  signal?: AbortSignal;
}

export async function pollJob(
  id: string,
  onTick: (job: Job) => void,
  opts: PollOptions = {},
): Promise<Job> {
  const {
    intervalMs: startInterval = 2_000,
    maxIntervalMs = 15_000,
    timeoutMs = 600_000,
    signal,
  } = opts;

  const deadline = Date.now() + timeoutMs;
  let interval = startInterval;
  let appActive = true;

  const handleAppState = (state: string) => {
    appActive = state === "active";
  };
  const subscription = AppState.addEventListener("change", handleAppState);

  try {
    for (;;) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

      if (Date.now() > deadline) {
        throw new ApiError(
          408,
          "poll_timeout",
          "Video generation is taking longer than expected. Please check back later.",
        );
      }

      if (!appActive) {
        await wait(1_000);
        continue;
      }

      try {
        const job = await api.getJob(id);
        onTick(job);
        if (TERMINAL_STATES.includes(job.state)) return job;
      } catch (err) {
        if (err instanceof AuthError) throw err;
        if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
        // Transient fetch failure — continue polling instead of crashing.
      }

      await wait(interval);
      interval = Math.min(interval * 1.5, maxIntervalMs);
    }
  } finally {
    subscription.remove();
  }
}
