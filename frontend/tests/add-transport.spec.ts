/**
 * E2E tests for the merged "Add transport" page.
 *
 * Flights and ground legs are two tables and two endpoints behind one form —
 * the type picker is what decides which API the submit hits, so the test that
 * matters is that switching type swaps the *place* inputs: an IATA combobox for
 * a flight, an OSM type-ahead for a train. Everything else is a field list.
 */

import { test, expect, type Page } from '@playwright/test';
import { BROWSER_STATE, requireSeededTrip } from './support/seed';

// Signed in as the account global-setup seeded a round trip for.
test.use({ storageState: BROWSER_STATE });

async function openSeededTrip(page: Page): Promise<void> {
  await page.goto(`/#/trips/${requireSeededTrip()}`);
  // The page has painted once its add-transport control has: the seeded trip
  // is the caller's own, so that control is always there.
  await expect(page.locator('a[href*="/add-transport"]').first()).toBeVisible();
}

async function openAddTransport(page: Page): Promise<void> {
  await openSeededTrip(page);
  await page.locator('a[href*="/add-transport"]').first().click();
  // The form is up once its type picker is.
  await expect(page.locator('.type-option').first()).toBeVisible();
}

test('the trip page offers one transport button, not two', async ({ page }) => {
  await openSeededTrip(page);

  expect(await page.locator('a[href*="/add-flight"]').count()).toBe(0);
  expect(await page.locator('a[href*="/add-transport"]').count()).toBeGreaterThan(0);
});

test('type picker swaps airport comboboxes for station lookups', async ({ page }) => {
  await openAddTransport(page);

  // Flight is the default: IATA comboboxes, no station type-ahead.
  await expect(page.locator('.airport-combobox')).toHaveCount(2);
  await expect(page.locator('.station-input')).toHaveCount(0);

  const trainOption = page.locator('.type-option').nth(1);
  await trainOption.click();

  await expect(page.locator('.station-input')).toHaveCount(2);
  await expect(page.locator('.airport-combobox')).toHaveCount(0);
  await expect(trainOption).toHaveClass(/selected/);
});

test('every field is visible, with the required ones marked', async ({ page }) => {
  await openAddTransport(page);

  // Nothing hidden behind a disclosure: cabin class is the field that used to be.
  await expect(page.locator('details')).toHaveCount(0);
  await expect(page.locator('select')).toBeVisible();

  // A flight needs its number, both airports and both times — five markers.
  await expect(page.locator('.form-label .req')).toHaveCount(5);

  // A ground leg needs both places and both times, and nothing else.
  await page.locator('.type-option').nth(1).click();
  await expect(page.locator('.form-label .req')).toHaveCount(4);
});

test('the form does not scroll sideways on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openAddTransport(page);
  // The date-range hint arrives with the trip lookup, after the picker: measure
  // the form in its finished state, hint included.
  await expect(page.locator('.form-hint').first()).toBeVisible();

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

// The trip's span bounds both pickers. This is only safe because the trip
// remembers the dates its owner declared: without that, adding the first leg
// collapses the span to that leg's day and the return leg would already fall
// outside its own trip.
test('date fields are bounded by the trip and say so', async ({ page }) => {
  await openAddTransport(page);

  const first = page.locator('input[type="datetime-local"]').first();
  // The bounds arrive with the trip lookup, after the form renders; reading the
  // attribute straight away raced it and skipped as "no dates". The seeded trip
  // always has dates, so wait for them. Date-granular at both ends: a bound
  // carrying a time greys out the whole boundary day, a broken-looking picker.
  await expect(first).toHaveAttribute('min', /T00:00$/);
  const min = await first.getAttribute('min');
  const max = await first.getAttribute('max');
  if (max !== null) {
    expect(max).toMatch(/T23:59$/);
    expect(min! <= max).toBe(true);
  }

  // Every date field carries the same bounds, not just the first.
  const all = page.locator('input[type="datetime-local"]');
  for (let i = 0; i < await all.count(); i++) {
    expect(await all.nth(i).getAttribute('min')).toBe(min);
    expect(await all.nth(i).getAttribute('max')).toBe(max);
  }

  // A greyed calendar needs an explanation on the page.
  await expect(page.locator('.form-hint').first()).toBeVisible();
});
