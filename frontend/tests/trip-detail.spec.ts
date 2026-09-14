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

  const docs = page.locator('.trip-section').filter({ has: page.locator('.section-note') });
  test.skip(await docs.count() === 0, 'Every section on this trip has content');
  const box = await docs.first().boundingBox();
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
