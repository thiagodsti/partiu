import { test, expect, type Page } from '@playwright/test';
import { BROWSER_STATE, requireSeededTrip } from './support/seed';

// Signed in as the account global-setup seeded a round trip for, on a phone.
test.use({ storageState: BROWSER_STATE, viewport: { width: 390, height: 844 } });

/**
 * Records every View Transition the page starts, with the direction
 * lib/viewTransition.ts set for it. Reading data-nav-direction off <html> after
 * the fact would race the transition finishing and clearing it.
 */
async function recordTransitions(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __transitions: string[] };
    w.__transitions = [];
    const original = document.startViewTransition?.bind(document);
    if (!original) return;
    document.startViewTransition = ((cb: ViewTransitionUpdateCallback) => {
      w.__transitions.push(document.documentElement.dataset.navDirection ?? '');
      return original(cb);
    }) as typeof document.startViewTransition;
  });
}

function transitions(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __transitions: string[] }).__transitions);
}

test('opening a flight pushes, and the back arrow pops', async ({ page }) => {
  await recordTransitions(page);
  const tripId = requireSeededTrip();
  await page.goto(`/#/trips/${tripId}`);
  await page.locator('.flight-row').first().click();

  await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}/flights/[\\w-]+$`));
  await expect.poll(() => transitions(page)).toEqual(['forward']);

  await page.locator('.nav-back').click();
  await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}$`));
  await expect(page.locator('.flight-row').first()).toBeVisible();
  await expect.poll(() => transitions(page)).toEqual(['forward', 'back']);
});

test('switching tabs cross-fades rather than sliding', async ({ page }) => {
  await recordTransitions(page);
  await page.goto('/#/trips');
  await expect(page.locator('.trip-card, .empty-state').first()).toBeVisible();
  await page.locator('.tab-bar a[href="#/stats"]').click();

  await expect(page).toHaveURL(/#\/stats$/);
  await expect.poll(() => transitions(page)).toEqual(['fade']);
});

test.describe('with reduced motion', () => {
  test.use({ contextOptions: { reducedMotion: 'reduce' } });

  test('navigates without starting a transition', async ({ page }) => {
    await recordTransitions(page);
    const tripId = requireSeededTrip();
    await page.goto(`/#/trips/${tripId}`);
    await page.locator('.flight-row').first().click();

    await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}/flights/[\\w-]+$`));
    expect(await transitions(page)).toEqual([]);
  });
});

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
