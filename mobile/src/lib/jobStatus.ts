import type { Job, JobState } from "@/api/types";

export const JOB_STATE_LABELS: Record<JobState, string> = {
  submitted: "Queued", running: "Creating", validating: "Checking photo", cleaning: "Preparing photo",
  planning: "Planning", awaiting_style_choice: "Choose a style", generating: "Creating",
  composing: "Preparing layout", reviewing: "Checking result", delivering: "Saving result",
  delivered: "Delivered", needs_reshoot: "New photo needed", awaiting_user_decision: "Review needed",
  aborted: "Cancelled", failed: "Failed",
};

export function isJobPending(job: Pick<Job, "state">): boolean {
  return !["delivered", "failed", "aborted"].includes(job.state);
}

export function jobRoute(job: Pick<Job, "id" | "state" | "campaignId" | "campaignVersion">): `/create/${string}` {
  if (job.campaignId && Number.isSafeInteger(job.campaignVersion) && job.campaignVersion! > 0) {
    return `/create/campaign-result?campaign=${encodeURIComponent(job.campaignId)}&version=${job.campaignVersion}`;
  }
  const screen = job.state === "delivered" ? "result" : job.state === "awaiting_style_choice" ? "style"
    : job.state === "needs_reshoot" ? "reshoot" : job.state === "awaiting_user_decision" ? "decision" : "generating";
  return `/create/${screen}?id=${encodeURIComponent(job.id)}`;
}
