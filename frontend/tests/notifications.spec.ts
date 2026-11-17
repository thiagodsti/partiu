/**
 * E2E tests for the notifications / inbox page.
 */

import { test, expect, type Page } from '@playwright/test';
import { BROWSER_STATE } from './support/seed';

const BASE = 'http://localhost:8000';

// The inbox belongs to someone; these tests never signed in, so on any server
// with an account they rendered the login page and failed.
test.use({ storageState: BROWSER_STATE });

async function serverAvailable(page: Page): Promise<boolean> {
  try {
    const res = await page.request.get(BASE, { timeout: 3000 });
    return res.status() < 500;
  } catch {
    return false;
  }
}

/** Opens the inbox and waits for it to render — networkidle is not "rendered",
 * and counting cards before the list paints reads an empty inbox. */
async function openInbox(page: Page) {
  await page.goto(`${BASE}/#/notifications`);
  await page.locator('.notif-card, .empty-state').first().waitFor();
}

test.beforeEach(async ({ page }) => {
  test.skip(!(await serverAvailable(page)), 'Server not available at http://localhost:8000');
});

test('notifications entry exists in the navigation', async ({ page }) => {
  await page.goto(BASE);
  await page.waitForLoadState('networkidle');
  // `.nav-item` is on both navigation surfaces — the desktop rail and the
  // mobile dock — and only one of them is on screen at any width, so the
  // :visible filter is what picks the one this viewport is actually showing.
  const notifTab = page.locator('.nav-item[href="#/notifications"]:visible');
  await expect(notifTab).toBeVisible();
});

test('notifications page loads without error', async ({ page }) => {
  await openInbox(page);
  // Should show either content or the empty state — never a crash
  const hasContent =
    (await page.locator('.notif-card').count()) > 0 ||
    (await page.locator('.empty-state').count()) > 0 ||
    (await page.locator('.main-content').count()) > 0;
  expect(hasContent).toBe(true);
});

test('notifications page shows empty state when inbox is empty', async ({ page }) => {
  await openInbox(page);
  const notifCards = page.locator('.notif-card');
  const emptyState = page.locator('.empty-state');
  // Either there are cards (real data) or the empty state is shown
  const hasCards = await notifCards.count() > 0;
  const hasEmpty = await emptyState.count() > 0;
  expect(hasCards || hasEmpty).toBe(true);
});

test('notification cards show title', async ({ page }) => {
  await openInbox(page);
  const cards = page.locator('.notif-card');
  test.skip(await cards.count() === 0, 'No notifications to check');
  const title = cards.first().locator('.notif-title');
  await expect(title).toBeVisible();
  const text = await title.textContent();
  expect(text?.trim().length).toBeGreaterThan(0);
});

test('notification card delete button works', async ({ page }) => {
  await openInbox(page);
  // Only notifications can be deleted; an invitation card is answered with
  // accept/reject instead and has no delete button.
  const deletable = page.locator('.notif-card:has(.notif-delete)');
  test.skip(await deletable.count() === 0, 'No notifications to delete');

  const before = await deletable.count();
  await deletable.first().locator('.notif-delete').click();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('.notif-card:has(.notif-delete)')).toHaveCount(before - 1);
});

test('invitation cards show accept and reject buttons', async ({ page }) => {
  await openInbox(page);
  // Invitations are shown as notif-unread cards at the top with action buttons
  const actionCards = page.locator('.notif-actions');
  test.skip(await actionCards.count() === 0, 'No pending invitations');
  const acceptBtn = actionCards.first().locator('button', { hasText: /accept/i });
  const rejectBtn = actionCards.first().locator('button', { hasText: /reject/i });
  await expect(acceptBtn).toBeVisible();
  await expect(rejectBtn).toBeVisible();
});

test('notifications tab badge reflects unread count', async ({ page }) => {
  // What the badge must say, from the same two sources the app sums.
  const unread = (await (await page.request.get(`${BASE}/api/notifications/inbox/count`)).json()).unread as number;
  const invitations = ((await (await page.request.get(`${BASE}/api/trips/invitations`)).json()) as unknown[]).length;
  const expected = unread + invitations;

  await page.goto(`${BASE}/#/trips`);
  await page.waitForLoadState('networkidle');
  const badge = page.locator('.nav-item[href="#/notifications"]:visible .nav-badge');
  if (expected === 0) {
    await expect(badge).toHaveCount(0);
  } else {
    await expect(badge).toHaveText(String(expected));
  }
});

// The badge counts unread notifications *and* pending invitations. Visiting the
// inbox marks the notifications read; an invitation stays until it is answered,
// so what is left on the badge afterwards is exactly the pending invitations.
test('visiting notifications page leaves only pending invitations on the badge', async ({ page }) => {
  await page.goto(BASE);
  await page.waitForLoadState('networkidle');

  const badge = page.locator('.nav-item[href="#/notifications"]:visible .nav-badge');
  // The badge arrives with the first inbox poll, after networkidle.
  await badge.waitFor({ timeout: 5000 }).catch(() => {});
  test.skip(await badge.count() === 0, 'No unread notifications to test badge clearing');

  // Navigate to the notifications page
  await openInbox(page);
  const pendingInvitations = await page.locator('.notif-actions').count();

  // Wait briefly for the mark-all-read API call to complete
  await page.waitForTimeout(500);

  // Navigate away and back to trips — badge should be gone
  await page.goto(`${BASE}/#/trips`);
  await page.waitForLoadState('networkidle');

  const badgeAfter = page.locator('.nav-item[href="#/notifications"]:visible .nav-badge');
  if (pendingInvitations === 0) {
    await expect(badgeAfter).toHaveCount(0);
  } else {
    await expect(badgeAfter).toHaveText(String(pendingInvitations));
  }
});
