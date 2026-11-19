import { test, expect } from '@playwright/test';
import { BROWSER_STATE } from './support/seed';

test.use({ storageState: BROWSER_STATE });

test('every iOS launch image the page declares is served', async ({ page, request }) => {
  await page.goto('/#/trips');
  await expect(page.locator('.trip-card, .empty-state').first()).toBeVisible();
  const hrefs = await page
    .locator('link[rel="apple-touch-startup-image"]')
    .evaluateAll((links) => links.map((l) => l.getAttribute('href') ?? ''));

  expect(hrefs.length).toBeGreaterThan(0);
  for (const href of hrefs) {
    const res = await request.get(href);
    expect(res.status(), href).toBe(200);
    expect(res.headers()['content-type'], href).toContain('image/png');
  }
});
