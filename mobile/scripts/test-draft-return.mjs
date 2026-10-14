import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const context = { exports: {}, URL };
vm.runInNewContext(ts.transpileModule(readFileSync("src/lib/draftReturn.ts", "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const { draftReturn } = context.exports;
for (const value of [null, ["/create/campaign"], "https://other.test/create/campaign?product=x&template=y", "//other.test/create/campaign", "/create/../../paywall?template=x", "/create/customize?template=x&mode=unknown", "/create/campaign?template=x"])
  assert.equal(draftReturn(value), null);
assert.equal(JSON.stringify(draftReturn("/create/campaign?product=x&template=y&redirect=https://other.test")), JSON.stringify({ pathname: "/create/campaign", params: { product: "x", template: "y" } }));
assert.equal(JSON.stringify(draftReturn("/create/customize?template=x&mode=photo")), JSON.stringify({ pathname: "/create/customize", params: { template: "x", mode: "photo" } }));
console.log("Draft return allowlist passed");
