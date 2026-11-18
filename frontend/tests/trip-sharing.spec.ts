import { test, expect } from '@playwright/test';
import { BROWSER_STATE, requireSeededServer, requireSeededTrip } from './support/seed';

// Paths only: Playwright resolves them against the configured baseURL, which
// is the server global setup prepared (E2E_BASE_URL when set).
test.use({ storageState: BROWSER_STATE });

test('delete trip flow', async ({ page }) => {
  // Deletes a trip made for the purpose: "the first card" was the seeded trip
  // every other browse spec opens.
  requireSeededServer();
  const res = await page.request.post('/api/trips', { data: { name: `E2E delete me ${Date.now()}` } });
  expect(res.ok(), `creating the trip to delete answered ${res.status()} ${await res.text()}`).toBeTruthy();
  const { id } = await res.json();
  await page.goto(`/#/trips/${id}`);

  // The caller owns this trip, so the owner's controls must be there.
  const deleteBtn = page.locator('button', { hasText: 'Delete Trip' });
  await expect(deleteBtn).toBeVisible();
  await deleteBtn.click();
  await page.locator('button', { hasText: 'Delete Trip' }).last().click();

  await expect(page).not.toHaveURL(new RegExp(`/trips/${id}`));
  expect((await page.request.get(`/api/trips/${id}`)).status()).toBe(404);
});

test('share trip panel opens', async ({ page }) => {
  await page.goto(`/#/trips/${requireSeededTrip()}`);

  const shareBtn = page.locator('button', { hasText: 'Share Trip' });
  await expect(shareBtn).toBeVisible();
  await shareBtn.click();

  await expect(page.locator('input[placeholder*="username" i]').first()).toBeVisible();
});
