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
import { BROWSER_STATE, requireSeededTrip } from './support/seed';

// The device profile supplies the viewport, `hasTouch` and `isMobile` — but not
// the browser: this project installs Chromium only (`npx playwright install
// chromium`), and iPhone profiles otherwise default to WebKit.
// Signed in as the account global-setup seeded a trip with a packing list for.
test.use({ ...devices['iPhone 13'], browserName: 'chromium', storageState: BROWSER_STATE });

/** Opens the seeded trip and returns its packing rows. */
async function packingRows(page: Page) {
  await page.goto(`/#/trips/${requireSeededTrip()}`);
  // The seeded trip always has packing items: wait for them to paint rather
  // than counting early and skipping every touch test as "no items".
  const rows = page.locator('.packing-item');
  await expect(rows.first()).toBeVisible();
  await rows.first().scrollIntoViewIfNeeded();
  return rows;
}

test('the row has no hover-gated controls where hover does not exist', async ({ page }) => {
  const rows = await packingRows(page);

  expect(await page.evaluate(() => matchMedia('(hover: hover)').matches)).toBe(false);

  const del = rows.first().locator('.packing-delete');
  await expect(del).toBeVisible();
  expect(await del.evaluate((el) => getComputedStyle(el).opacity)).toBe('1');
});

test('the checkbox hit area covers the full height of the row', async ({ page }) => {
  const rows = await packingRows(page);
  const checkbox = rows.first().locator('.checkbox');

  const measure = () =>
    checkbox.evaluate(async (el) => {
      // Centre the box, then wait two frames so the probe sees that layout.
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const box = el.getBoundingClientRect();
      const cx = box.left + box.width / 2;
      const cy = box.top + box.height / 2;
      // How far above and below the drawn box a tap still lands on the button.
      // A probe outside the viewport finds no element at all, which is a miss —
      // `?.` alone would turn it into `undefined !== null`, a hit.
      const hits = (dy: number) =>
        (document.elementFromPoint(cx, cy + dy)?.closest('.checkbox') ?? null) !== null;
      return { drawn: Math.round(box.height), up: hits(-14), down: hits(14) };
    });

  // Measured until it holds, not once: content above the list (the map, the
  // cover photo) can finish loading after the scroll and push the row
  // off-screen, where both probes find nothing — a diagnostic caught the box
  // at y=1630 on one run in twenty. A hit area that really shrank never
  // passes, so retrying loses no coverage.
  await expect.poll(async () => {
    const r = await measure();
    return r.up && r.down;
  }).toBe(true);

  expect((await measure()).drawn).toBeLessThanOrEqual(24); // still drawn small, on purpose
});

test('one tap toggles an item', async ({ page }) => {
  const rows = await packingRows(page);

  const row = rows.first();
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
