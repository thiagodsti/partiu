/**
 * E2E tests for the planner on a phone.
 *
 * Reported: an idea added on the phone could be dragged onto a day on the
 * laptop but not on the phone. HTML drag and drop is a mouse feature — a touch
 * never fires `dragstart` — so the planner picks an item up on a press and
 * hold instead and carries it under the finger. The phone's day cards were
 * not drop targets at all either.
 *
 * The touches are sent through CDP (`Input.dispatchTouchEvent`) rather than
 * `locator.dispatchEvent`, so they are real touches: hit-testing, scrolling
 * and the touch-then-click sequence all behave as on a device.
 */

import { test, expect, devices, type Page } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

// Chromium only: this project installs no WebKit (see packing-touch.spec.ts).
test.use({ ...devices['Pixel 5'], browserName: 'chromium' });

const USER = ACCOUNTS.planOwner.username;
const PASS = ACCOUNTS.planOwner.password;

async function centre(page: Page, selector: string) {
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`${selector} is not on screen`);
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test('an idea is pressed, held and dragged onto a day', async ({ page }) => {
  await signInPage(page, USER, PASS);
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E planner touch', start_date: '2027-06-10', end_date: '2027-06-11' },
  });
  expect(created.ok()).toBeTruthy();
  const tripId = (await created.json()).id as string;

  try {
    await page.goto(`/#/trips/${tripId}/plan`);
    await expect(page.locator('.day-card-m').first()).toBeVisible({ timeout: 15000 });

    // Added through the keyboard's Done button, i.e. a form submission.
    const ideaBox = page.locator('.panel .item-draft').nth(0);
    await ideaBox.fill('Fado night');
    await ideaBox.evaluate((el) => (el as HTMLInputElement).form?.requestSubmit());
    await expect(page.locator('.panel .item', { hasText: 'Fado night' })).toBeVisible();

    // On a phone the ideas sit below every day, so the drag has to scroll the
    // page: holding the item at the top edge does that.
    const firstDay = page.locator('.day-card-m .dm-items').first();
    const idea = page.locator('.panel .item', { hasText: 'Fado night' });
    // Centred: at the bottom edge it would sit under the floating tab bar.
    await idea.evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
    const from = await centre(page, '.panel .item:has-text("Fado night")');

    const cdp = await page.context().newCDPSession(page);
    const touch = (type: 'touchStart' | 'touchMove' | 'touchEnd', p?: { x: number; y: number }) =>
      cdp.send('Input.dispatchTouchEvent', { type, touchPoints: p ? [p] : [] });
    await touch('touchStart', from);
    await page.waitForTimeout(500); // past the long press
    await expect(page.locator('.touch-ghost')).toHaveText('Fado night');
    for (let i = 1; i <= 6; i++) {
      await touch('touchMove', { x: from.x, y: from.y + ((20 - from.y) * i) / 6 });
    }
    await expect
      .poll(async () => (await firstDay.boundingBox())?.y ?? -1, { timeout: 15000 })
      .toBeGreaterThan(120);
    const to = await centre(page, '.day-card-m .dm-items');
    await touch('touchMove', to);
    await touch('touchEnd');

    await expect(firstDay.locator('.item', { hasText: 'Fado night' })).toBeVisible();
    // The drop ended the gesture: the editor did not open on the lift.
    await expect(page.locator('.modal-backdrop:not(.closed)')).toHaveCount(0);
    await expect
      .poll(async () => {
        const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
        return plan.items.find((i: { title: string }) => i.title === 'Fado night')?.date;
      })
      .toBe('2027-06-10');
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('a quick swipe over an item scrolls instead of picking it up', async ({ page }) => {
  await signInPage(page, USER, PASS);
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E planner swipe', start_date: '2027-06-10', end_date: '2027-06-11' },
  });
  const tripId = (await created.json()).id as string;
  try {
    await page.request.post(`/api/trips/${tripId}/plan/items`, { data: { title: 'Swipe me', status: 'idea' } });
    await page.goto(`/#/trips/${tripId}/plan`);
    const item = page.locator('.panel .item', { hasText: 'Swipe me' });
    await item.evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
    const p = await centre(page, '.panel .item:has-text("Swipe me")');

    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [p] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: p.x, y: p.y - 60 }] });
    await page.waitForTimeout(500);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });

    await expect(page.locator('.touch-ghost')).toHaveCount(0);
    const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
    expect(plan.items.find((i: { title: string }) => i.title === 'Swipe me').date).toBeNull();
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('an idea is brought onto a day from the day itself', async ({ page }) => {
  await signInPage(page, USER, PASS);
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E planner pick', start_date: '2027-06-10', end_date: '2027-06-11' },
  });
  const tripId = (await created.json()).id as string;
  try {
    await page.request.post(`/api/trips/${tripId}/plan/items`, { data: { title: 'Tram 28', status: 'idea' } });
    await page.goto(`/#/trips/${tripId}/plan`);
    const firstDay = page.locator('.day-card-m .dm-items').first();
    const picker = firstDay.locator('.idea-pick');
    await expect(picker).toBeVisible({ timeout: 15000 });
    await picker.selectOption({ label: '💡 Tram 28' });

    await expect(firstDay.locator('.item', { hasText: 'Tram 28' })).toBeVisible();
    // The last idea is scheduled, so there is nothing left to offer.
    await expect(picker).toHaveCount(0);
    await expect
      .poll(async () => {
        const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
        return plan.items.find((i: { title: string }) => i.title === 'Tram 28')?.date;
      })
      .toBe('2027-06-10');
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});
