import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 320, height: 568 }, locale: 'en-US' });
const errors = [], writes = [];
page.on('pageerror', error => errors.push(error.message));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lYwT+QAAAABJRU5ErkJggg==', 'base64');
await page.route('**/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (!['GET', 'HEAD'].includes(request.method())) writes.push({ path, body: request.postDataJSON() });
  let body;
  if (path === '/v1/account') body = { email: 'languages@example.com' };
  else if (path === '/v1/products/product') body = { name: 'Çilek — Açúcar & Niño', assetKey: 'original' };
  else if (path === '/v1/products/product/approved-image') body = { image: { assetKey: 'approved', version: 1 } };
  else if (path.startsWith('/v1/assets/')) { await route.fulfill({ contentType: 'image/png', body: png }); return; }
  else if (path === '/v1/campaign-pack/quote') body = { available: true, priceCredits: 3, scope: 'campaign_pack' };
  else { await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' }); return; }
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
});

async function chooseLanguage(name) {
  await page.goto('http://localhost:8098/language');
  await page.getByRole('radio', { name: new RegExp(name) }).click({ timeout: 120000 });
  await expect(page.getByRole('radio', { name: new RegExp(name) })).toBeChecked();
}
async function fitsScreen() {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'No horizontal page overflow');
}

try {
  await mkdir('.expo/language-check', { recursive: true });
  for (const [name, account, code] of [['Türkçe', 'Hesap', 'tr'], ['Português', 'Conta', 'pt-BR'], ['Español', 'Cuenta', 'es'], ['English', 'Account', 'en']]) {
    await chooseLanguage(name);
    await page.reload();
    await expect(page.getByRole('radio', { name: new RegExp(name) })).toBeChecked();
    await page.goto('http://localhost:8098/account');
    await expect(page.getByText(account, { exact: true }).first()).toBeVisible();
    await fitsScreen();
    await page.screenshot({ path: `.expo/language-check/account-${code}-320.png` });
  }
  await page.goto('http://localhost:8098/create/campaign?product=product&template=pedestal_spin');
  await page.getByRole('button', { name: 'Campaign language: English', exact: true }).click();
  await page.getByRole('button', { name: 'Português (Brasil)', exact: true }).click();
  const offer = 'Çilek — Açúcar & Niño · R$ 12,50';
  await page.getByRole('textbox', { name: 'Offer', exact: true }).fill(offer);
  await page.getByRole('button', { name: 'Campaign purpose & free preview', exact: true }).click();
  await page.getByRole('button', { name: /Use conversation focus/i }).click();
  await expect(page.getByRole('textbox', { name: 'Offer', exact: true })).toHaveValue(offer);
  const cta = await page.getByRole('textbox', { name: 'Call to action', exact: true }).inputValue();
  assert.match(cta, /mensagem|Fale|Entre|detalhes/i, 'Portuguese suggestion while UI stays English');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Campaign language: Português (Brasil)', exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Offer', exact: true })).toHaveValue(offer);
  await chooseLanguage('Türkçe');
  await page.goto('http://localhost:8098/create/campaign?product=product&template=pedestal_spin');
  await expect(page.getByRole('button', { name: /Português \(Brasil\)/ })).toBeVisible();
  assert.ok((await page.locator('textarea,input').evaluateAll(nodes => nodes.map(node => node.value))).includes(offer));
  assert.equal(writes.length, 0, 'Language and draft changes do not start generation or spend credits');
  await page.setViewportSize({ width: 430, height: 932 });
  await page.screenshot({ path: '.expo/language-check/campaign-tr-pt-BR-430.png' });
  await fitsScreen();
  assert.deepEqual(errors, []);
  console.log('Languages browser: four UI languages, persistence, exact merchant text, independent Portuguese campaign suggestions and no paid request passed');
} finally { await browser.close(); }
