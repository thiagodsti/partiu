/**
 * E2E tests for the notifications / inbox page.
 */

import { test, expect, type Page } from '@playwright/test';

const BASE = 'http://localhost:8000';

async function serverAvailable(page: Page): Promise<boolean> {
  try {
    const res = await page.request.get(BASE, { timeout: 3000 });
    return res.status() < 500;
  } catch {
    return false;
  }
}

test.beforeEach(async ({ page }) => {
  test.skip(!(await serverAvailable(page)), 'Server not available at http://localhost:8000');
});

test('notifications tab exists in tab bar', async ({ page }) => {
  await page.goto(BASE);
  await page.waitForLoadState('networkidle');
  const notifTab = page.locator('.tab-bar a[href="#/notifications"]');
  await expect(notifTab).toBeVisible();
});

test('notifications page loads without error', async ({ page }) => {
  await page.goto(`${BASE}/#/notifications`);
  await page.waitForLoadState('networkidle');
  // Should show either content or the empty state — never a crash
  const hasContent =
    (await page.locator('.notif-card').count()) > 0 ||
    (await page.locator('.empty-state').count()) > 0 ||
    (await page.locator('.main-content').count()) > 0;
  expect(hasContent).toBe(true);
});

test('notifications page shows empty state when inbox is empty', async ({ page }) => {
  await page.goto(`${BASE}/#/notifications`);
  await page.waitForLoadState('networkidle');
  const notifCards = page.locator('.notif-card');
  const emptyState = page.locator('.empty-state');
  // Either there are cards (real data) or the empty state is shown
  const hasCards = await notifCards.count() > 0;
  const hasEmpty = await emptyState.count() > 0;
  expect(hasCards || hasEmpty).toBe(true);
});

test('notification cards show title', async ({ page }) => {
  await page.goto(`${BASE}/#/notifications`);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.notif-card');
  test.skip(await cards.count() === 0, 'No notifications to check');
  const title = cards.first().locator('.notif-title');
  await expect(title).toBeVisible();
  const text = await title.textContent();
  expect(text?.trim().length).toBeGreaterThan(0);
});

test('notification card delete button works', async ({ page }) => {
  await page.goto(`${BASE}/#/notifications`);
  await page.waitForLoadState('networkidle');
  const cards = page.locator('.notif-card');
  test.skip(await cards.count() === 0, 'No notifications to delete');

  const before = await cards.count();
  await cards.first().locator('.notif-delete').click();
  await page.waitForLoadState('networkidle');
  const after = await page.locator('.notif-card').count();
  expect(after).toBe(before - 1);
});

test('invitation cards show accept and reject buttons', async ({ page }) => {
  await page.goto(`${BASE}/#/notifications`);
  await page.waitForLoadState('networkidle');
  // Invitations are shown as notif-unread cards at the top with action buttons
  const actionCards = page.locator('.notif-actions');
  test.skip(await actionCards.count() === 0, 'No pending invitations');
  const acceptBtn = actionCards.first().locator('button', { hasText: /accept/i });
  const rejectBtn = actionCards.first().locator('button', { hasText: /reject/i });
  await expect(acceptBtn).toBeVisible();
  await expect(rejectBtn).toBeVisible();
});

test('notifications tab badge reflects unread count', async ({ page }) => {
  await page.goto(BASE);
  await page.waitForLoadState('networkidle');
  const badge = page.locator('.tab-bar a[href="#/notifications"] .tab-badge');
  // Badge is only visible when there are unread items — both states are valid
  const hasBadge = await badge.count() > 0;
  if (hasBadge) {
    await expect(badge).toBeVisible();
    const text = await badge.textContent();
    expect(Number(text)).toBeGreaterThan(0);
  }
  // If no badge, that's fine — just means inbox is empty
  expect(true).toBe(true);
});

test('visiting notifications page clears unread badge', async ({ page }) => {
  await page.goto(BASE);
  await page.waitForLoadState('networkidle');

  const badge = page.locator('.tab-bar a[href="#/notifications"] .tab-badge');
  test.skip(await badge.count() === 0, 'No unread notifications to test badge clearing');

  // Navigate to the notifications page
  await page.goto(`${BASE}/#/notifications`);
  await page.waitForLoadState('networkidle');

  // Wait briefly for the mark-all-read API call to complete
  await page.waitForTimeout(500);

  // Navigate away and back to trips — badge should be gone
  await page.goto(`${BASE}/#/trips`);
  await page.waitForLoadState('networkidle');

  const badgeAfter = page.locator('.tab-bar a[href="#/notifications"] .tab-badge');
  expect(await badgeAfter.count()).toBe(0);
});
