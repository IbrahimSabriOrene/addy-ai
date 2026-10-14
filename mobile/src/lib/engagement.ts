import { req, USE_MOCK } from "@/api/client";

export async function trackEngagement(name: "browse" | "customize" | "result" | "export") {
  if (USE_MOCK) return;
  // Server enforces opt-in and stores only one event of each kind per day.
  await req("/v1/account/engagement/events", { method: "POST", body: JSON.stringify({ name }) }).catch(() => {});
}
