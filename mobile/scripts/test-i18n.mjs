import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const transpile = file => ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
const catalogs = {};
for (const name of ["core", "campaign", "account", "billing"]) {
  const context = { exports: {} };
  vm.runInNewContext(transpile(`../src/i18n/messages-${name}.ts`), context);
  catalogs[`./messages-${name}`] = context.exports;
  for (const [source, translations] of Object.entries(context.exports.default)) {
    assert.equal(translations.length, 3, source);
    const placeholders = value => [...value.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort();
    for (const value of translations) {
      assert.ok(value.trim(), source);
      assert.deepEqual(placeholders(value), placeholders(source), `Placeholder mismatch: ${source}`);
    }
  }
}
const runtime = { exports: {}, Intl, require: name => catalogs[name] };
vm.runInNewContext(transpile("../src/i18n/runtime.ts"), runtime);
const api = runtime.exports;
assert.equal(api.normalizeLocale("tr-TR"), "tr");
assert.equal(api.normalizeLocale("es-MX"), "es");
assert.equal(api.normalizeLocale("pt_BR"), "pt-BR");
assert.equal(api.normalizeLocale("ja-JP"), "en");
assert.equal(api.translate("Generate · {count} credits", { count: 2 }, "tr"), "Oluştur · 2 kredi");
assert.equal(api.translate("Generate · {count} credits", { count: 2 }, "en"), "Generate · 2 credits");
assert.equal(api.translate("Unknown source {value}", { value: "$& {count}" }, "es"), "Unknown source $& {count}");
assert.equal(api.translate("toString", undefined, "tr"), "toString");
assert.equal(api.translate("Brand £19.99 İpek / ação / mañana", undefined, "es"), "Brand £19.99 İpek / ação / mañana");

let state = [], slot = 0, mounted = false, persisted = "tr", fail = false;
const React = {
  createContext: initial => ({ Provider: "Provider", initial }),
  createElement: (type, props, ...children) => ({ type, props, children }),
  useContext: context => context.initial,
  useState(initial) { const index = slot++; if (!(index in state)) state[index] = initial; return [state[index], value => { state[index] = value; }]; },
  useEffect(effect) { if (!mounted) { mounted = true; effect(); } },
};
const provider = { exports: {}, require(name) {
  if (name === "./runtime") return api;
  if (name === "react") return React;
  if (name.includes("async-storage")) return { getItem: async key => { assert.equal(key, api.LOCALE_STORAGE_KEY); return persisted; }, setItem: async (key, value) => { assert.equal(key, api.LOCALE_STORAGE_KEY); if (fail) throw Error("storage unavailable"); persisted = value; } };
  throw Error(name);
} };
vm.runInNewContext(transpile("../src/i18n/index.tsx"), provider);
const render = () => { slot = 0; return provider.exports.I18nProvider({ children: "screen" }); };
assert.equal(render(), null, "Wait for saved language before rendering screens");
await new Promise(resolve => setImmediate(resolve));
assert.equal(render().props.value.locale, "tr");
await render().props.value.setLocale("pt-BR");
assert.equal(persisted, "pt-BR");
assert.equal(render().props.value.tr("Home"), "Início");
fail = true;
await assert.rejects(render().props.value.setLocale("es"));
assert.equal(render().props.value.locale, "pt-BR", "Storage failure must not pretend preference was saved");
fail = false; persisted = "not-supported"; state = []; mounted = false;
render(); await new Promise(resolve => setImmediate(resolve));
assert.equal(render().props.value.locale, api.deviceLocale());
console.log("i18n: all catalog placeholders, locale fallback, interpolation, persistence and storage failure passed");
