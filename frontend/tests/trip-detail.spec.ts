import { test, expect, type Page } from '@playwright/test';
import { BROWSER_STATE, seededTripId, stopoverTripId } from './support/seed';

const BASE_URL = 'http://localhost:8000';

// Signed in as the account global-setup seeded a round trip for.
test.use({ storageState: BROWSER_STATE });

/** Opens the seeded trip: ARN→FRA→LIS out, LIS→ARN back, with an expense. */
async function goToFirstTrip(page: Page): Promise<boolean> {
  const tripId = seededTripId();
  if (!tripId) return false;
  await page.goto(`${BASE_URL}/#/trips/${tripId}`);
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

test('outbound divider shows travelling time', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  const outbound = page.locator('.section-divider-label', { hasText: 'Outbound' }).first();
  await expect(outbound).toBeVisible();
  const label = await outbound.textContent() ?? '';
  // "travelling", not "flying", since a leg can be a train (LegDivider).
  expect(label).toContain('travelling');
});

test('round trip has return divider', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  await expect(page.locator('.section-divider-label', { hasText: 'Return' }).first()).toBeVisible();
});

test('connection badge visible for multi-leg trip', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  // The seeded outbound changes planes in Frankfurt.
  const badge = page.locator('.connection-badge').first();
  await expect(badge).toBeVisible();
  const label = badge.locator('.connection-badge-label');
  await expect(label).toBeVisible();
  const text = await label.textContent() ?? '';
  expect(text.includes('at') || text.includes('m')).toBe(true);
});

test('no total shown for long stopover', async ({ page }) => {
  const tripId = stopoverTripId();
  test.skip(!tripId, 'No trip with 24h+ stopover found');
  await page.goto(`${BASE_URL}/#/trips/${tripId}`);
  await page.waitForLoadState('networkidle');

  // The seeded stopover waits 25h in Copenhagen. A wait that long always
  // crosses a day, so the legs are separated by a date divider rather than a
  // connection badge — which is why this test used to look for a 24h+ badge
  // and skip on every trip: no such badge can be drawn.
  await expect(page.locator('.flight-row')).toHaveCount(2);
  await expect(page.locator('.connection-badge')).toHaveCount(0);

  // legStats drops the total past 24h: door to door is no longer one journey.
  const outbound = page.locator('.section-divider-label', { hasText: 'Outbound' }).first();
  await expect(outbound).toBeVisible();
  expect(await outbound.textContent() ?? '').not.toContain('total');
});

test('clicking flight row opens flight detail', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');
  await page.waitForSelector('.flight-row', { state: 'visible', timeout: 5000 });
  await page.locator('.flight-row').first().click();
  await page.waitForLoadState('networkidle');
  expect(page.url()).toContain('/flights/');
});

// The desktop layout is two independent flows (spine + aside), not one balanced
// grid. In a grid, sections land in shared row bands and a short card leaves a
// hole beneath itself until the band closes — which is the blank space this
// layout exists to remove. Measure the gaps rather than the CSS.
test('desktop columns stack without row-band holes', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');

  const spine = page.locator('.trip-spine');
  const aside = page.locator('.trip-aside');
  await expect(spine).toBeVisible();
  await expect(aside).toBeVisible();

  // The two wrappers really are side by side at this width.
  const spineBox = await spine.boundingBox();
  const asideBox = await aside.boundingBox();
  expect(spineBox!.x + spineBox!.width).toBeLessThanOrEqual(asideBox!.x + 1);

  // Within a column, consecutive cards are separated by the section margin
  // (--space-md, 16px) and nothing more. 48px leaves room for a collapsed
  // section's own spacing without tolerating a real hole.
  for (const column of ['.trip-spine', '.trip-aside']) {
    const boxes = await page.locator(`${column} > .trip-section:visible`).evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom };
      }),
    );
    for (let i = 1; i < boxes.length; i++) {
      expect(boxes[i].top - boxes[i - 1].bottom).toBeLessThan(48);
    }
  }
});

test('an empty documents section collapses onto its header row', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');

  // Documents specifically: other empty sections (stays, say) carry advisory
  // lines under their note and are not meant to fold onto one row. Found
  // without the compact class, so losing that class fails here, not skips.
  const docs = page.locator('.trip-section-documents');
  await expect(docs).toBeVisible();
  test.skip(await docs.locator('.section-note').count() === 0, 'This trip has documents');
  await expect(docs).toHaveClass(/trip-section-compact/);
  const box = await docs.boundingBox();
  expect(box!.height).toBeLessThan(100);
});

// The expenses list sizes its rows off its own width (a container query), so the
// sidebar column gets the stacked layout the phone gets. If it ever falls back
// to a viewport query, descriptions start getting clipped here first.
test('expense descriptions are not clipped in the sidebar column', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');

  const descs = page.locator('.expense-desc');
  test.skip(await descs.count() === 0, 'No expenses on this trip');

  const clipped = await descs.evaluateAll((els) =>
    els.filter((el) => el.scrollWidth > el.clientWidth + 1).length,
  );
  expect(clipped).toBe(0);
});

// Desktop and phone want Documents in different places, and the DOM can only be
// in one order — below the breakpoint the wrappers go `display: contents` and
// CSS `order` moves Documents down next to the notes. Assert the painted order.
test('documents sits directly above the trip notes on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');

  const order = await page.$$eval('.trip-section', (els) =>
    els
      .map((el) => ({
        top: el.getBoundingClientRect().top + window.scrollY,
        name: el.classList.contains('trip-section-documents')
          ? 'documents'
          : el.classList.contains('trip-section-tail')
            ? 'tail'
            : 'other',
      }))
      .sort((a, b) => a.top - b.top)
      .map((x) => x.name),
  );

  expect(order.indexOf('documents')).toBeGreaterThan(-1);
  expect(order.indexOf('documents')).toBeLessThan(order.indexOf('tail'));
  // …and nothing else comes between them.
  expect(order[order.indexOf('documents') + 1]).toBe('tail');
});

// A rated trip on a phone: five 2.75rem stars plus "Limpar avaliação" are wider
// than the content column, and before the row was allowed to wrap they pushed
// the whole document sideways. Nothing on this page may exceed the viewport.
test('the trip page never scrolls sideways on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');

  // Rate the trip so the clear button is on screen for the measurement.
  const star = page.locator('.rating-half').last();
  if (await star.count() > 0) {
    await star.click();
    await page.waitForTimeout(200);
  }

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

test('an empty section shows its whole explanation, not an ellipsis', async ({ page }) => {
  const found = await goToFirstTrip(page);
  test.skip(!found, 'No trips in database');

  const notes = page.locator('.section-note');
  test.skip(await notes.count() === 0, 'Every section on this trip has content');
  const clipped = await notes.evaluateAll((els) =>
    els.filter((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1).length,
  );
  expect(clipped).toBe(0);
});
