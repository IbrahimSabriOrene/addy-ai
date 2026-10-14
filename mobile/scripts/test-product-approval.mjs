import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const values = [], calls = [];
let index = 0, mounted = false, approved = null, conflict = false, uploads = 0;
class ApiError extends Error { constructor(status) { super("Version changed"); this.status = status; } }
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const slot = index++; if (!(slot in values)) values[slot] = initial; return [values[slot], value => { values[slot] = value; }]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const context = { exports: {}, require(name) {
  if (name === "@/i18n") { const tr = (source, params) => source.replace(/\{(\w+)\}/g, (match, key) => params?.[key] === undefined ? match : String(params[key])); return { useI18n: () => ({ locale: "en", tr }), translate: tr }; }
  if (name === "react") return React;
  if (name === "react-native") return { Image: "Image", View: "View" };
  if (name === "expo-image-picker") return { launchImageLibraryAsync: async () => ({ canceled: false, assets: [{ uri: "file:replacement" }] }) };
  if (name === "@/api/client") return { ApiError,
    uploadImage: async () => { uploads++; return "replacement"; },
    req: async (path, init) => {
      calls.push({ path, init });
      if (!init) return { image: approved };
      if (conflict) throw new ApiError(409);
      const body = JSON.parse(init.body);
      approved = { assetKey: body.assetKey, version: body.expectedVersion + 1 };
      return approved;
    },
  };
  return { Button: "Button", Text: "Text", ProductPreview: "ProductPreview" };
} };
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/ApproveProductImage.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, context);
const render = () => { index = 0; return context.exports.ApproveProductImage({ productId: "product", sourceAssetKey: "original" }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(node => node.props?.label === label);
const settle = () => new Promise(resolve => setImmediate(resolve));
render(); await settle();
assert.equal(calls.filter(call => call.init).length, 0, "Opening review must not approve automatically");
button("Approve this photo for campaigns").props.onPress(); await settle();
assert.deepEqual(approved, { assetKey: "original", version: 1 });
assert.equal(uploads, 0);
assert.equal(button("Approve this photo for campaigns"), undefined);
button("Choose replacement photo").props.onPress(); await settle();
assert.equal(approved.assetKey, "original", "Picking must not replace before approval");
conflict = true;
button("Approve this photo for campaigns").props.onPress(); await settle();
assert.equal(uploads, 1);
assert.equal(button("Approve this photo for campaigns"), undefined, "A stale version requires reload");
approved = { assetKey: "other-device", version: 2 };
button("Reload approved image").props.onPress(); await settle();
conflict = false;
button("Approve this photo for campaigns").props.onPress(); await settle();
assert.deepEqual(approved, { assetKey: "replacement", version: 3 });
assert.equal(uploads, 1, "Retry reuses the completed upload");
assert.ok(calls.every(call => call.path === "/v1/products/product/approved-image"));
console.log("Product approval requires explicit review, preserves versions and reuses uploads after conflict");
