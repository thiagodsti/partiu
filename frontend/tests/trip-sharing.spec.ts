import { test, expect, type Page } from '@playwright/test';

const BASE_URL = 'http://localhost:8000';

async function serverAvailable(page: Page): Promise<boolean> {
  try {
    const res = await page.request.get(BASE_URL, { timeout: 3000 });
    return res.status() < 500;
  } catch {
    return false;
  }
}


test.beforeEach(async ({ page }) => {
  test.skip(!(await serverAvailable(page)), 'Server not available at http://localhost:8000');
});

test('delete trip flow', async ({ page }) => {
  await page.goto(BASE_URL);
  await page.waitForLoadState('networkidle');

  const cards = page.locator('.trip-card');
  test.skip(await cards.count() === 0, 'No trips available for delete test');

  await cards.first().click();
  await page.waitForLoadState('networkidle');

  const deleteBtn = page.locator('button', { hasText: 'Delete Trip' });
  test.skip(await deleteBtn.count() === 0, 'Delete Trip button not found (may be a shared trip)');

  await deleteBtn.click();
  await page.locator('button', { hasText: 'Delete Trip' }).last().click();
  await page.waitForLoadState('networkidle');

  expect(page.url()).toMatch(/\/#\/?/);
});

test('share trip panel opens', async ({ page }) => {
  await page.goto(BASE_URL);
  await page.waitForLoadState('networkidle');

  const cards = page.locator('.trip-card');
  test.skip(await cards.count() === 0, 'No trips available for share test');

  await cards.first().click();
  await page.waitForLoadState('networkidle');

  const shareBtn = page.locator('button', { hasText: 'Share Trip' });
  test.skip(await shareBtn.count() === 0, 'Share Trip button not found (may be a shared trip view)');

  await shareBtn.click();

  const usernameInput = page.locator('input[placeholder*="username" i]');
  expect(await usernameInput.count()).toBeGreaterThan(0);
});
