import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 320, height: 568 } });
const errors = [], writes = [];
page.on("pageerror", e => errors.push(e.message));
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lYwT+QAAAABJRU5ErkJggg==", "base64");
const video = await readFile("public/previews/skincare_glow.preview.mp4");
let result = { published: false, channel: "instagram", messages: null, orders: null, useful: null }, version = 0;
await page.route("**/v1/**", async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  let body;
  if (path === "/v1/account") body = { email: "growth@example.com" };
  else if (path === "/v1/products/product") body = { name: "Bakery fixture", assetKey: "original" };
  else if (path === "/v1/products/product/approved-image") body = { image: { assetKey: "approved", version: 1 } };
  else if (path.startsWith("/v1/assets/")) { await route.fulfill({ contentType: "image/png", body: png }); return; }
  else if (path === "/v1/campaign-pack/quote") body = { available: true, priceCredits: 3, scope: "campaign_pack" };
  else if (path === "/v1/campaigns/campaign/generations/1/video") { await route.fulfill({ contentType: "video/mp4", body: video }); return; }
  else if (path === "/v1/campaigns/campaign/generations/1") body = { campaignId: "campaign", campaignVersion: 1, jobId: "job", resultVersion: "2", state: "delivered", priceCredits: 3, outputs: { video: { state: "ready", url: "/v1/campaigns/campaign/generations/1/video", mimeType: "video/mp4", width: 1080, height: 1920 }, copy: { state: "ready", caption: "Weekend offer", cta: "Visit us" } } };
  else if (path === "/v1/campaigns/campaign/outcome") {
    if (request.method() === "PUT") { const value = request.postDataJSON(); assert.equal(value.expectedVersion, version); const { expectedVersion, ...fields } = value; result = fields; version++; writes.push(path); }
    body = { result, version };
  } else { await route.fulfill({ status: 404, contentType: "application/json", body: "{}" }); return; }
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
});
try {
  await page.goto("http://localhost:8098/create/campaign?product=product&template=pedestal_spin");
  await page.getByRole("button", { name: "Campaign purpose & free preview", exact: true }).click({ timeout: 120000 });
  await page.getByRole("button", { name: "Weekend campaign", exact: true }).click();
  await page.getByRole("textbox", { name: "Offer", exact: true }).fill("Weekend bread box £12");
  await page.getByRole("button", { name: "Use conversation focus", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Offer", exact: true })).toHaveValue("Weekend bread box £12");
  await expect(page.getByRole("textbox", { name: "Call to action", exact: true })).toHaveValue("Message us for details");
  await page.getByRole("button", { name: "Preview draft · no credits", exact: true }).click();
  await page.getByText("Draft composition, not a generated video", { exact: false }).scrollIntoViewIfNeeded();
  await mkdir(".expo/growth-check", { recursive: true });
  await page.screenshot({ path: ".expo/growth-check/preview-320.png" });
  assert.equal(writes.length, 0);
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto("http://localhost:8098/create/campaign-result?campaign=campaign&version=1");
  await page.getByRole("button", { name: "Show placement guide", exact: true }).click();
  await page.getByText("Illustrative guide only", { exact: false }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: ".expo/growth-check/guide-430.png" });
  await page.getByRole("button", { name: "Publish, measure & use again", exact: true }).click();
  await page.getByRole("switch", { name: "Published campaign", exact: true }).click();
  await page.getByRole("textbox", { name: "Campaign orders", exact: true }).fill("2");
  await page.getByRole("button", { name: "Save observed results", exact: true }).click();
  await page.getByText("Your results were saved.", { exact: false }).waitFor();
  assert.equal(result.orders, 2); assert.equal(result.published, true);
  await page.goto("http://localhost:8098/for-business?segment=bakery");
  await page.getByRole("button", { name: "Explore examples for my business", exact: true }).click();
  await expect(page).toHaveURL(/category=food/);
  assert.deepEqual(errors, []);
  console.log("Growth browser: 320px free preview, exact offer preserved, 430px placement guide, outcome save and segment entry passed");
} finally { await browser.close(); }
