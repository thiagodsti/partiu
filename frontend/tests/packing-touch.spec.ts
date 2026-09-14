/**
 * E2E tests for the shared checkbox on a touch screen, exercised through the
 * packing list.
 *
 * These cover a bug where every checkbox needed tapping twice. Two things
 * caused it, and both are asserted here:
 *
 *   1. The row's delete button was hidden behind `:hover`. On a phone that
 *      control is unreachable — there is no hover — and, worse, it made the
 *      row's appearance depend on hover, which is what makes a touch browser
 *      spend the first tap applying the hover state instead of dispatching
 *      the click. The fix guards the rule with `@media (hover: hover)`.
 *
 *   2. The checkbox was a 20px target, which is half a fingertip. Its hit
 *      area is now grown to the height of the row with a pseudo-element,
 *      without changing the drawn size.
 *
 * The first-tap-hovers behaviour itself is a real-device quirk that headless
 * Chromium does not reproduce — it dispatches the click directly. What *is*
 * checkable here is the cause: that nothing in the row is hover-gated when
 * hover is unavailable, and that a near-miss tap still lands.
 */

import { test, expect, devices, type Page } from '@playwright/test';

const BASE = 'http://localhost:8000';

// The device profile supplies the viewport, `hasTouch` and `isMobile` — but not
// the browser: this project installs Chromium only (`npx playwright install
// chromium`), and iPhone profiles otherwise default to WebKit.
test.use({ ...devices['iPhone 13'], browserName: 'chromium' });

async function serverAvailable(page: Page): Promise<boolean> {
  try {
    const res = await page.request.get(BASE, { timeout: 3000 });
    return res.status() < 500;
  } catch {
    return false;
  }
}

/** Opens the first trip and returns its packing rows, or null when there are none. */
async function packingRows(page: Page) {
  await page.goto(`${BASE}/#/trips`);
  await page.waitForLoadState('networkidle');
  const card = page.locator('.card-link').first();
  if ((await card.count()) === 0) return null;
  await card.click();
  await page.waitForLoadState('networkidle');
  const rows = page.locator('.packing-item');
  if ((await rows.count()) === 0) return null;
  await rows.first().scrollIntoViewIfNeeded();
  return rows;
}

test.beforeEach(async ({ page }) => {
  test.skip(!(await serverAvailable(page)), 'Server not available at http://localhost:8000');
});

test('the row has no hover-gated controls where hover does not exist', async ({ page }) => {
  const rows = await packingRows(page);
  test.skip(rows === null, 'No trip with packing items in database');

  expect(await page.evaluate(() => matchMedia('(hover: hover)').matches)).toBe(false);

  const del = rows!.first().locator('.packing-delete');
  await expect(del).toBeVisible();
  expect(await del.evaluate((el) => getComputedStyle(el).opacity)).toBe('1');
});

test('the checkbox hit area covers the full height of the row', async ({ page }) => {
  const rows = await packingRows(page);
  test.skip(rows === null, 'No trip with packing items in database');

  const reach = await rows!.first().locator('.checkbox').evaluate((el) => {
    const box = el.getBoundingClientRect();
    const cx = box.left + box.width / 2;
    const cy = box.top + box.height / 2;
    // How far above and below the drawn box a tap still lands on the button.
    const hits = (dy: number) =>
      document.elementFromPoint(cx, cy + dy)?.closest('.checkbox') !== null;
    return { drawn: Math.round(box.height), up: hits(-14), down: hits(14) };
  });

  expect(reach.drawn).toBeLessThanOrEqual(24); // still drawn small, on purpose
  expect(reach.up).toBe(true);
  expect(reach.down).toBe(true);
});

test('one tap toggles an item', async ({ page }) => {
  const rows = await packingRows(page);
  test.skip(rows === null, 'No trip with packing items in database');

  const row = rows!.first();
  const before = await row.evaluate((el) => el.classList.contains('is-checked'));
  await row.locator('.checkbox').tap();
  await expect
    .poll(() => row.evaluate((el) => el.classList.contains('is-checked')))
    .toBe(!before);

  // Put it back, so the test leaves the list as it found it.
  await row.locator('.checkbox').tap();
  await expect
    .poll(() => row.evaluate((el) => el.classList.contains('is-checked')))
    .toBe(before);
});
