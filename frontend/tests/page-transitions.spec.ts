import { test, expect, type Page } from '@playwright/test';
import { BROWSER_STATE, requireSeededTrip } from './support/seed';

// Signed in as the account global-setup seeded a round trip for, on a phone.
test.use({ storageState: BROWSER_STATE, viewport: { width: 390, height: 844 } });

interface Recorded {
  direction: string;
  /** `<pseudo-element> <animation-name>` for every animation the transition ran. */
  animations: string[];
}

/**
 * Records every View Transition the page starts: the direction
 * lib/viewTransition.ts set for it, and — once the pseudo-element tree exists —
 * the animations the browser is actually running on it. Reading
 * data-nav-direction off <html> after the fact would race the transition
 * finishing and clearing it, and the direction alone would still pass with the
 * stylesheet's slide rules deleted.
 */
async function recordTransitions(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __transitions: Recorded[] };
    w.__transitions = [];
    const original = document.startViewTransition?.bind(document);
    if (!original) return;
    document.startViewTransition = ((cb: ViewTransitionUpdateCallback) => {
      const entry: Recorded = { direction: document.documentElement.dataset.navDirection ?? '', animations: [] };
      w.__transitions.push(entry);
      const transition = original(cb);
      transition.ready.then(() => {
        entry.animations = document
          .getAnimations()
          .filter((a) => (a.effect as KeyframeEffect | null)?.pseudoElement?.startsWith('::view-transition'))
          .map((a) => `${(a.effect as KeyframeEffect).pseudoElement} ${(a as CSSAnimation).animationName}`);
      });
      return transition;
    }) as typeof document.startViewTransition;
  });
}

async function transitions(page: Page): Promise<Recorded[]> {
  return page.evaluate(() => (window as unknown as { __transitions: Recorded[] }).__transitions);
}

async function directions(page: Page): Promise<string[]> {
  return (await transitions(page)).map((t) => t.direction);
}

/** The animations of the nth transition, once its pseudo-tree has been read. */
async function animationsOf(page: Page, n: number): Promise<string[]> {
  await expect.poll(async () => (await transitions(page))[n]?.animations.length ?? 0).toBeGreaterThan(0);
  return (await transitions(page))[n].animations;
}

test('opening a flight pushes, and the back arrow pops', async ({ page }) => {
  await recordTransitions(page);
  const tripId = requireSeededTrip();
  await page.goto(`/#/trips/${tripId}`);
  await page.locator('.flight-row').first().click();

  await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}/flights/[\\w-]+$`));
  await expect.poll(() => directions(page)).toEqual(['forward']);
  const push = await animationsOf(page, 0);
  expect(push).toContain('::view-transition-new(root) vt-enter');
  expect(push).toContain('::view-transition-old(root) vt-recede');
  // The dock is its own snapshot, and nothing slides it.
  expect(push.some((a) => a.includes('(tab-bar)'))).toBe(true);
  expect(push.filter((a) => a.includes('(tab-bar)') && / vt-/.test(a))).toEqual([]);

  await page.locator('.nav-back').click();
  await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}$`));
  await expect(page.locator('.flight-row').first()).toBeVisible();
  await expect.poll(() => directions(page)).toEqual(['forward', 'back']);
  const pop = await animationsOf(page, 1);
  // The same keyframes run in reverse: the popped page slides back off.
  expect(pop).toContain('::view-transition-old(root) vt-enter');
  expect(pop).toContain('::view-transition-new(root) vt-recede');
});

test('switching tabs cross-fades rather than sliding', async ({ page }) => {
  await recordTransitions(page);
  await page.goto('/#/trips');
  await expect(page.locator('.trip-card, .empty-state').first()).toBeVisible();
  await page.locator('.tab-bar a[href="#/stats"]').click();

  await expect(page).toHaveURL(/#\/stats$/);
  await expect.poll(() => directions(page)).toEqual(['fade']);
  const fade = await animationsOf(page, 0);
  expect(fade.filter((a) => / vt-/.test(a))).toEqual([]);
  expect(fade.some((a) => a.startsWith('::view-transition-new(root)'))).toBe(true);
});

test.describe('on a wide screen', () => {
  test.use({ viewport: { width: 1200, height: 900 } });

  test('a push cross-fades instead of sliding across the monitor', async ({ page }) => {
    await recordTransitions(page);
    const tripId = requireSeededTrip();
    await page.goto(`/#/trips/${tripId}`);
    await page.locator('.flight-row').first().click();

    await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}/flights/[\\w-]+$`));
    await expect.poll(() => directions(page)).toEqual(['forward']);
    const push = await animationsOf(page, 0);
    expect(push.filter((a) => / vt-/.test(a))).toEqual([]);
    // The rail replaces the dock here, and holds still the same way.
    expect(push.some((a) => a.includes('(side-rail)'))).toBe(true);
  });
});

test.describe('with reduced motion', () => {
  test.use({ contextOptions: { reducedMotion: 'reduce' } });

  test('navigates without starting a transition', async ({ page }) => {
    await recordTransitions(page);
    const tripId = requireSeededTrip();
    await page.goto(`/#/trips/${tripId}`);
    await page.locator('.flight-row').first().click();

    await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}/flights/[\\w-]+$`));
    expect(await directions(page)).toEqual([]);
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
