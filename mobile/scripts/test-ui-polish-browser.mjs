import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 320, height: 568 } });
const errors = [], writes = [];
page.on('pageerror', e => errors.push(e.message));
await page.addInitScript(() => localStorage.setItem('addy:ui-language', 'tr'));
await page.route('**/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (request.method() !== 'GET') writes.push(path);
  if (path === '/v1/audit/video') return route.fulfill({ contentType: 'video/mp4', body: await readFile('public/previews/skincare_glow.preview.mp4') });
  if (path.startsWith('/v1/assets/')) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lYwT+QAAAABJRU5ErkJggg==', 'base64') });
  const body = path === '/v1/account' ? { email: 'ui@example.com' }
    : path === '/v1/products/product' ? { name: 'Çilek — Açúcar & Niño', assetKey: 'original' }
    : path.endsWith('/approved-image') ? { image: { assetKey: 'approved', version: 1 } }
    : path === '/v1/campaign-pack/quote' ? { available: true, priceCredits: 3, scope: 'campaign_pack' }
    : path === '/v1/campaigns/campaign/generations/1' ? { campaignId: 'campaign', campaignVersion: 1, jobId: 'job', resultVersion: '2', state: 'delivered', priceCredits: 3, outputs: { video: { state: 'ready', url: '/v1/audit/video', mimeType: 'video/mp4', width: 1080, height: 1920 }, copy: { state: 'ready', caption: 'Exact offer R$ 12,50', cta: 'Visit us' } } } : null;
  await route.fulfill({ status: body ? 200 : 404, contentType: 'application/json', body: JSON.stringify(body ?? {}) });
});
const go = route => page.goto('http://localhost:8098/' + route);
await mkdir('.expo/ui-polish', { recursive: true });
try {
  for (const segment of ['bakery', 'handmade']) {
    await go('for-business?segment=' + segment);
    await expect(page.getByLabel('Stil önizleme fotoğrafı')).toBeVisible();
    await expect(page.getByText('Stil önizlemesi kullanılamıyor')).toHaveCount(0);
  }
  await go('sign-in');
  await expect(page.getByText('Bağımsız çevrim içi satıcılar için')).toHaveCount(0);
  await page.getByRole('button', { name: /Addy AI hakkında/ }).click();
  await expect(page.getByText('Bağımsız çevrim içi satıcılar için')).toBeVisible();
  await page.getByRole('button', { name: /Addy AI hakkında/ }).click();
  await page.screenshot({ path: '.expo/ui-polish/sign-in-320.png' });
  await go('home');
  await expect(page.getByText(/Good morning|Good afternoon|Good evening/)).toHaveCount(0);
  await go('language');
  assert.ok((await page.getByRole('button', { name: 'Geri', exact: true }).boundingBox()).height >= 44);
  await go('onboarding');
  await expect(page.getByText('Net bir ürün fotoğrafıyla başlayın ve paylaşmadan önce her sonucu inceleyin.')).toBeInViewport();
  await page.screenshot({ path: '.expo/ui-polish/onboarding-320.png' });
  await go('create/campaign?product=product&template=pedestal_spin');
  await expect(page.getByRole('button', { name: 'Oluştur · 3 kredi', exact: true })).toBeEnabled();
  const details = page.getByRole('button', { name: 'Paket ve kredi ayrıntıları', exact: true });
  const bounds = await details.boundingBox();
  assert.ok(bounds.y >= 400, 'Fixed footer leaves at least 400px for the brief at 320x568');
  await page.screenshot({ path: '.expo/ui-polish/campaign-320.png' });
  await details.click();
  await expect(page.getByText('Krediler şimdi ayrılır;', { exact: false }).last()).toBeVisible();
  await page.getByRole('button', { name: 'Kapat', exact: true }).click();
  const offer = page.getByRole('textbox', { name: 'Teklif', exact: true });
  await offer.fill('Çilek · R$ 12,50');
  await page.getByRole('button', { name: 'Diğer seçenekler', exact: true }).click();
  await page.getByRole('radio', { name: 'Renk #F8D7E8', exact: true }).click();
  await expect(offer).toHaveValue('Çilek · R$ 12,50');
  await page.reload();
  await expect(offer).toHaveValue('Çilek · R$ 12,50');
  await page.getByRole('button', { name: 'Diğer seçenekler', exact: true }).click();
  await expect(page.getByRole('radio', { name: 'Renk #F8D7E8', exact: true })).toBeChecked();
  await go('create/campaign-result?campaign=campaign&version=1');
  await expect(page.locator('video')).toBeInViewport();
  await expect(page.getByText('Video with sound', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Güncel kampanyayı düzenle' })).toHaveCount(0);
  await page.screenshot({ path: '.expo/ui-polish/campaign-result-320.png' });
  await page.getByRole('button', { name: 'Diğer', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Güncel kampanyayı düzenle' })).toBeVisible();
  await page.setViewportSize({ width: 740, height: 360 });
  await go('create/decision?id=job_1');
  await expect(page.getByText('Bu sonuç nasıl?', { exact: true })).toBeInViewport();
  const cancel = page.getByRole('button', { name: 'İptal', exact: true });
  await cancel.scrollIntoViewIfNeeded();
  await expect(cancel).toBeInViewport();
  assert.ok((await cancel.boundingBox()).height >= 44);
  await page.screenshot({ path: '.expo/ui-polish/decision-landscape.png' });
  assert.deepEqual(writes, [], 'Read-only UI interactions never start paid generation or save server data');
  assert.deepEqual(errors, []);
  console.log('UI polish: previews, targets, onboarding, compact footer, exact offer/color persistence, media-first results, landscape decision, no paid calls passed');
} finally { await browser.close(); }
