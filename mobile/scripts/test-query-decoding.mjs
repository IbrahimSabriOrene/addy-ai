import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const query = require("query-string");
assert.deepEqual({ ...query.parse("offer=%C3%A7ay+%26+%E2%82%AC&tag=a&tag=b") }, {
  offer: "çay & €", tag: ["a", "b"],
});
const params = { offer: "50% indirim 🎁", returnTo: "/create/campaign?productId=123" };
assert.deepEqual({ ...query.parse(query.stringify(params)) }, params);
assert.equal(query.parse("broken=%E0%A4%A").broken, "%E0%A4%A");
// Bound the vulnerable dependency's worst-case input in a separate process so
// a future downgrade fails the check instead of hanging the test runner.
execFileSync(process.execPath, ["-e", `
  const assert = require("node:assert/strict");
  const query = require("query-string");
  const malformed = "%FF".repeat(20000);
  assert.equal(query.parse("offer=" + malformed).offer, malformed);
`], { cwd: new URL("..", import.meta.url), timeout: 5000 });
console.log("Query decoding preserves route parameters and bounds malformed-input processing");
