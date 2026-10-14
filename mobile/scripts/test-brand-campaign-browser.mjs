import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 320, height: 568 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
let profile = { name: "", color: "#FFFFFF", font: "sans", contact: "", logoAssetKey: null }, version = 0;
const posts = [], png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lYwT+QAAAABJRU5ErkJggg==", "base64");
const source = { id: "source", productId: "product", imageVersion: 2, assetKey: "approved", version: 1,
  brief: { offer: "20% off last weekend", caption: "Previous caption", cta: "Shop now", instructions: "Slow camera", color: "#123456", font: "serif", contact: "shop.example", style: { id: "spin", version: 1 } } };
const video = await readFile("public/previews/skincare_glow.preview.mp4");
await page.route("**/v1/**", async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  let body;
  if (path === "/v1/account") body = { email: "browser@example.com" };
  else if (path === "/v1/account/brand") {
    if (request.method() === "PUT") {
      const { expectedVersion, ...next } = request.postDataJSON();
      assert.equal(expectedVersion, version); profile = next; version++;
    }
    body = { profile, version };
  } else if (path === "/v1/products/product") body = { name: "Fixture product", assetKey: "original" };
  else if (path === "/v1/products/product/approved-image") body = { image: { assetKey: "approved", version: 2 } };
  else if (path === "/v1/catalogue") body = { items: [{ id: "spin", name: "Spin", version: 1, outputKinds: ["video"], previews: {} }] };
  else if (path === "/v1/campaign-pack/quote") body = { available: true, priceCredits: 3, scope: "campaign_pack", settlement: "Fixture" };
  else if (path === "/v1/campaigns/source/generations/1/video") { await route.fulfill({ contentType: "video/mp4", body: video }); return; }
  else if (path === "/v1/campaigns/source/generations/1") body = { campaignId: "source", campaignVersion: 1, jobId: "job", resultVersion: "fixture", priceCredits: 3, state: "delivered", outputs: {
    video: { state: "ready", url: "/v1/campaigns/source/generations/1/video", mimeType: "video/mp4", width: 1080, height: 1920 },
    copy: { state: "ready", caption: "Caption", cta: "Shop" },
  } };
  else if (path.startsWith("/v1/assets/")) { await route.fulfill({ contentType: "image/png", body: png }); return; }
  else if (path === "/v1/campaigns/source") body = source;
  else if (path === "/v1/campaigns" && request.method() === "POST") {
    posts.push({ key: request.headers()["idempotency-key"], body: request.postDataJSON() });
    if (posts.length === 1) { await route.abort("failed"); return; }
    body = { id: "copy" };
  } else { await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ message: `Fixture not found: ${path}` }) }); return; }
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
});
try {
  await page.goto("http://localhost:8098/brand");
  await page.getByRole("textbox", { name: "Brand name", exact: true }).waitFor({ timeout: 120000 });
  await page.getByRole("textbox", { name: "Brand name", exact: true }).fill("Small Shop");
  await page.getByRole("textbox", { name: "Brand color (#RRGGBB)", exact: true }).fill("#123456");
  await page.getByRole("button", { name: "Serif", exact: true }).click();
  await page.getByRole("textbox", { name: "Contact shown on layouts", exact: true }).fill("shop.example");
  await page.getByRole("button", { name: "Save brand profile", exact: true }).click();
  await page.getByText("Brand saved.", { exact: false }).waitFor();
  await page.reload();
  await page.getByRole("textbox", { name: "Brand name", exact: true }).waitFor();
  assert.equal(await page.getByRole("textbox", { name: "Brand name", exact: true }).inputValue(), "Small Shop");
  await mkdir(".expo/feature-check", { recursive: true });
  await page.screenshot({ path: ".expo/feature-check/brand-small.png" });
  await page.goto("http://localhost:8098/create/campaign?product=product&template=pedestal_spin");
  await page.getByRole("button", { name: "Apply saved brand", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Background color (#RRGGBB)", exact: true })).toHaveValue("#123456");
  await page.getByRole("button", { name: "Brand options", exact: true }).click();
  assert.equal(await page.getByRole("textbox", { name: "Contact shown on layouts", exact: true }).inputValue(), "shop.example");
  await page.goto("http://localhost:8098/create/campaign-copy?campaign=source");
  const save = page.getByRole("button", { name: "Save campaign copy · no credits", exact: true });
  await save.waitFor(); assert.equal(await save.isDisabled(), true);
  await page.getByRole("textbox", { name: "Offer for the new campaign", exact: true }).fill("15% off this weekend");
  await page.getByRole("button", { name: "I reviewed the offer, dates and copy", exact: true }).click();
  await save.scrollIntoViewIfNeeded();
  await page.screenshot({ path: ".expo/feature-check/copy-small.png" });
  await save.click();
  await page.getByRole("button", { name: "Retry same copy", exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Retry same copy", exact: true }).click();
  await page.getByRole("button", { name: "Open copied campaign", exact: true }).waitFor();
  assert.deepEqual(posts[0], posts[1]);
  assert.equal(posts[0].body.offer, "15% off this weekend");
  assert.equal(posts[0].body.font, "serif");
  assert.equal(posts[0].body.imageVersion, 2);
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto("http://localhost:8098/create/campaign-result?campaign=source&version=1");
  await page.getByRole("button", { name: "Compare with original product", exact: true }).click();
  await page.getByText("Original product", { exact: true }).waitFor();
  await page.getByText("Campaign result", { exact: true }).waitFor();
  await page.screenshot({ path: ".expo/feature-check/comparison-large.png" });
  await page.getByRole("button", { name: "Close product comparison", exact: true }).click();
  assert.deepEqual(errors, []);
  console.log("320px browser: brand persists; copy requires review and survives a lost response/reload with the same command");
} finally { await browser.close(); }
