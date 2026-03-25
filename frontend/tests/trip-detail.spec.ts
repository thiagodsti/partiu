import { test, expect, type Page } from '@playwright/test';

const BASE_URL = 'http://localhost:8000';

async function goToFirstTrip(page: Page): Promise<boolean> {
  await page.goto(`${BASE_URL}/#/trips`);
  await page.waitForLoadState('networkidle');
  const card = page.locator('.trip-card').first();
  if (await card.count() === 0) return false;
  await card.click();
  await page.waitForLoadState('networkidle');
  return true;
}

test('homepage loads trips view', async ({ page }) => {
  await page.goto(BASE_URL);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.trip-card');
  const empty = page.locator('.empty-state');
  const hasCards = await cards.count() > 0;
  const hasEmpty = await empty.count() > 0;
  expect(hasCards || hasEmpty).toBe(true);
});

test('trips list renders cards or empty state', async ({ page }) => {
  await page.goto(`${BASE_URL}/#/trips`);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.trip-card');
  const empty = page.locator('.empty-state');
  const hasCards = await cards.count() > 0;
  const hasEmpty = await empty.count() > 0;
  expect(hasCards || hasEmpty).toBe(true);
});

test('trip detail has outbound divider', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  await expect(page.locator('.section-divider-label', { hasText: 'Outbound' }).first()).toBeVisible();
});

test('trip detail shows flight rows', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  await expect(page.locator('.flight-row').first()).toBeVisible();
});

test('flight row shows route arrow', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  const route = page.locator('.flight-route').first();
  await expect(route).toBeVisible();
  await expect(route.locator('.flight-route-arrow')).toBeVisible();
});

test('outbound divider shows flying time', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  const outbound = page.locator('.section-divider-label', { hasText: 'Outbound' }).first();
  await expect(outbound).toBeVisible();
  const label = await outbound.textContent() ?? '';
  expect(label).toContain('flying');
});

test('round trip has return divider', async ({ page }) => {
  await page.goto(`${BASE_URL}/#/trips`);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.trip-card');
  test.skip(await cards.count() === 0, 'No trips in database');

  const count = Math.min(await cards.count(), 8);
  for (let i = 0; i < count; i++) {
    await cards.nth(i).click();
    await page.waitForLoadState('networkidle');
    const ret = page.locator('.section-divider-label', { hasText: 'Return' });
    if (await ret.count() > 0) {
      await expect(ret.first()).toBeVisible();
      return;
    }
    await page.goBack();
    await page.waitForLoadState('networkidle');
  }
  test.skip(true, 'No round-trip found in first 8 trips');
});

test('connection badge visible for multi-leg trip', async ({ page }) => {
  await page.goto(`${BASE_URL}/#/trips`);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.trip-card');
  test.skip(await cards.count() === 0, 'No trips in database');

  const count = Math.min(await cards.count(), 15);
  for (let i = 0; i < count; i++) {
    await cards.nth(i).click();
    await page.waitForLoadState('networkidle');
    const badges = page.locator('.connection-badge');
    if (await badges.count() > 0) {
      await expect(badges.first()).toBeVisible();
      const label = badges.first().locator('.connection-badge-label');
      await expect(label).toBeVisible();
      const text = await label.textContent() ?? '';
      expect(text.includes('at') || text.includes('m')).toBe(true);
      return;
    }
    await page.goBack();
    await page.waitForLoadState('networkidle');
  }
  test.skip(true, 'No multi-leg trip found in first 15 trips');
});

test('no total shown for long stopover', async ({ page }) => {
  await page.goto(`${BASE_URL}/#/trips`);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.trip-card');
  test.skip(await cards.count() === 0, 'No trips in database');

  const count = Math.min(await cards.count(), 15);
  for (let i = 0; i < count; i++) {
    await cards.nth(i).click();
    await page.waitForLoadState('networkidle');
    const badges = page.locator('.connection-badge-label');
    const badgeCount = await badges.count();
    for (let j = 0; j < badgeCount; j++) {
      const text = await badges.nth(j).textContent() ?? '';
      const m = text.match(/(\d+)h/);
      if (m && parseInt(m[1]) >= 24) {
        const outbound = page.locator('.section-divider-label', { hasText: 'Outbound' }).first();
        const label = await outbound.textContent() ?? '';
        expect(label).not.toContain('total');
        return;
      }
    }
    await page.goBack();
    await page.waitForLoadState('networkidle');
  }
  test.skip(true, 'No trip with 24h+ stopover found');
});

test('clicking flight row opens flight detail', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  await page.waitForSelector('.flight-row', { state: 'visible', timeout: 5000 });
  await page.locator('.flight-row').first().click();
  await page.waitForLoadState('networkidle');
  expect(page.url()).toContain('/flights/');
});
