import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../src/lib/jobStatus.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const context = { exports: {} };
vm.runInNewContext(source, context);
const { jobRoute, isJobPending, JOB_STATE_LABELS } = context.exports;
for (const state of Object.keys(JOB_STATE_LABELS)) {
  const job = { id: "job/with spaces", state };
  const expected = ({ delivered: "result", awaiting_style_choice: "style", needs_reshoot: "reshoot", awaiting_user_decision: "decision" })[state] ?? "generating";
  assert.equal(jobRoute(job), `/create/${expected}?id=job%2Fwith%20spaces`);
  assert.equal(isJobPending(job), !["delivered", "failed", "aborted"].includes(state));
  assert.equal(jobRoute({ ...job, campaignId: "campaign/id", campaignVersion: 2 }), "/create/campaign-result?campaign=campaign%2Fid&version=2");
}
console.log("All job states route to their saved result, gate or status; terminal states are not pending");
