import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const compile = (path, require) => {
  const context = { exports: {}, require, URLSearchParams };
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText, context);
  return context.exports;
};
const runtime = compile("../src/i18n/runtime.ts", name => compile(`../src/i18n/${name.slice(2)}.ts`));
const state = [], updates = [];
let slot = 0;
const React = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useState(initial) { const index = slot++; if (!(index in state)) state[index] = initial; return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }]; },
};
const i18n = { ...runtime, useI18n: () => ({ locale: runtime.getLocale(), tr: runtime.translate }) };
const require = name => {
  if (name === "@/i18n") return i18n;
  if (name === "react") return React;
  if (name === "react-native") return { View: "View" };
  return { Text: "Text", Button: "Button", ProductPreview: "ProductPreview", CampaignLanguage: "CampaignLanguage" };
};
const { CampaignPlanner } = compile("../src/components/CampaignPlanner.tsx", require);
let brief = { offer: "R$ 49,90 — 20% até sábado", caption: "My own caption", cta: "", color: "#FFFFFF" };
const render = () => { slot = 0; return CampaignPlanner({ brief, assetKey: "approved", disabled: false, onChange: patch => { updates.push(patch); brief = { ...brief, ...patch }; } }); };
const nodes = tree => !tree || typeof tree !== "object" ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
const button = label => nodes(render()).find(n => n.props?.label === label);
runtime.setCurrentLocale("en");
const language = nodes(render()).find(n => n.type === "CampaignLanguage");
assert.equal(language.props.value, "en", "Old campaigns default to English without changing stored fields");
language.props.onChange("pt-BR");
assert.deepEqual(Object.keys(updates[0]), ["campaignLanguage"]);
assert.equal(brief.offer, "R$ 49,90 — 20% até sábado");
assert.equal(brief.caption, "My own caption");
assert.equal(runtime.getLocale(), "en", "Campaign selection does not change the interface language");
button("Campaign purpose & free preview").props.onPress();
button("Introduce a product").props.onPress();
assert.equal(brief.cta, "Conheça a coleção", "Suggestion follows campaign language, not English interface");
button("Weekend campaign").props.onPress();
assert.equal(brief.cta, "Conheça a coleção", "Choosing a purpose never overwrites existing copy");
for (const locale of ["en", "tr", "pt-BR", "es"]) {
  runtime.setCurrentLocale(locale);
  button(runtime.translate("Use purchase focus")).props.onPress();
  assert.equal(brief.cta, "Compre este produto");
  assert.equal(brief.caption, "R$ 49,90 — 20% até sábado\nCompre este produto");
  assert.equal(brief.offer, "R$ 49,90 — 20% até sábado", "Exact offer is preserved in every interface language");
}
console.log("Campaign language stays independent; four interface languages preserve exact offers, editable copy and pt-BR suggestions.");

// Render the actual paid-action components with a server quote, without submitting.
for (const locale of ["en", "tr", "pt-BR", "es"]) {
  runtime.setCurrentLocale(locale);
  for (const [file, exported, key] of [
    ["GenerateNewCampaign", "GenerateNewCampaign", "Generate · {credits} credits"],
    ["GenerateCampaign", "GenerateCampaign", "Generate pack · {credits} credits"],
  ]) {
    for (const pending of [false, true]) {
      let next = 0;
      const values = [pending ? { key: "same-request", body: { expectedVersion: 1, confirmedCredits: 7 } } : null,
        { campaignVersion: 1, available: true, priceCredits: 3, scope: "campaign_pack", settlement: "" }, null, false, "", 0];
      const module = compile(`../src/components/${file}.tsx`, name => {
        if (name === "react") return { ...React, useRef: () => ({ current: "" }), useEffect() {}, useState: () => [values[next++], () => {}] };
        if (name === "expo-router") return { useRouter: () => ({ push() {} }) };
        if (name === "@/theme/ThemeProvider") return { useTheme: () => ({ colors: {} }) };
        return require(name);
      });
      const tree = module[exported]({ campaignId: "campaign", version: 1, product: "product", template: "template", body: {}, disabled: false, onLockedChange() {}, onStartNew() {} });
      const expected = pending ? file === "GenerateNewCampaign"
        ? runtime.translate("Retry saved generation · {credits} credits", { credits: 7 }) : runtime.translate("Retry saved generation")
        : runtime.translate(key, { credits: 3 });
      assert.ok(nodes(tree).some(node => node.props?.label === expected), `${file} ${locale} renders translated ${pending ? "retry" : "quote"} action with exact credits`);
    }
  }
}
console.log("Actual campaign generation and retry buttons preserve server prices in all four interface languages.");
