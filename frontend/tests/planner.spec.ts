/**
 * E2E tests for the trip planner (#/trips/:id/plan).
 *
 * What matters end to end: a city added to the route frames its days and joins
 * the trip's destinations, an item typed into a day lands on that date with its
 * time, and the planner and the trip page's day cards are one list — what is
 * added on either shows on the other.
 */

import { test, expect } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

const USER = ACCOUNTS.planOwner.username;
const PASS = ACCOUNTS.planOwner.password;

test('plan a day and see it mirrored on the trip page', async ({ page }) => {
  await signInPage(page, USER, PASS);

  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E planner', start_date: '2027-05-10', end_date: '2027-05-13' },
  });
  expect(created.ok()).toBeTruthy();
  const tripId = (await created.json()).id as string;

  await page.goto(`/#/trips/${tripId}/plan`);
  await expect(page.locator('.board')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.day-head')).toHaveCount(4);

  // A city on the route, typed by hand (no geocoder needed).
  await page.getByTestId('add-stop').click();
  await page.locator('.stop-form input').first().fill('Lisbon');
  const dates = page.locator('.stop-form input[type=date]');
  await dates.nth(0).fill('2027-05-10');
  await dates.nth(1).fill('2027-05-13');
  await page.locator('.stop-form button[type=submit]').click();
  await expect(page.locator('.stop-chip', { hasText: 'Lisbon' })).toBeVisible();
  await expect(page.locator('.city-tag', { hasText: 'Lisbon' }).first()).toBeVisible();

  // "09:30 Belém Tower" on the first day: the time is split off the title.
  const firstDay = page.locator('.items-cell').first();
  await firstDay.locator('.item-draft').fill('09:30 Belém Tower');
  await firstDay.locator('.item-draft').press('Enter');
  await expect(firstDay.locator('.item', { hasText: 'Belém Tower' })).toBeVisible();

  const plan = await (await page.request.get(`/api/trips/${tripId}/plan`)).json();
  const item = plan.items.find((i: { title: string }) => i.title === 'Belém Tower');
  expect(item).toMatchObject({ date: '2027-05-10', time: '09:30' });
  const trip = await (await page.request.get(`/api/trips/${tripId}`)).json();
  expect(trip.destinations.map((d: { name: string }) => d.name)).toContain('Lisbon');

  // Back to the trip: the day card shows the planner's item...
  await page.getByTestId('save-and-back').click();
  await expect(page).toHaveURL(new RegExp(`#/trips/${tripId}$`));
  const card = page.locator('.day-card').first();
  await expect(card.locator('.dc-title')).toHaveValue('Belém Tower', { timeout: 15000 });
  await expect(card.locator('.dc-city', { hasText: 'Lisbon' })).toBeVisible();

  // ...and an item added on the card is in the planner.
  await card.locator('.dc-add').fill('Pastéis de Belém');
  await card.locator('.dc-add').press('Enter');
  await expect(card.locator('.dc-title').nth(1)).toHaveValue('Pastéis de Belém');
  await page.goto(`/#/trips/${tripId}/plan`);
  await expect(
    page.locator('.items-cell').first().locator('.item', { hasText: 'Pastéis de Belém' }),
  ).toBeVisible({ timeout: 15000 });

  await page.request.delete(`/api/trips/${tripId}`);
});

test("an item's notes open from the day card, with links shortened", async ({ page }) => {
  await signInPage(page, USER, PASS);
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E planner notes', start_date: '2027-05-20', end_date: '2027-05-21' },
  });
  const tripId = (await created.json()).id as string;
  try {
    await page.request.post(`/api/trips/${tripId}/plan/items`, {
      data: {
        title: 'Fado night',
        date: '2027-05-20',
        status: 'todo',
        notes: 'Reservar aqui https://www.example.com/restaurants/tasca-do-chico?ref=a1b2c3d4e5',
      },
    });
    await page.goto(`/#/trips/${tripId}`);
    const card = page.locator('.day-card').first();
    await expect(card.locator('.dc-title')).toHaveValue('Fado night', { timeout: 15000 });

    // Closed by default: a note is often a link far longer than the card.
    await expect(card.locator('.dc-notes')).toHaveCount(0);
    await card.locator('.dc-notes-toggle').click();
    const link = card.locator('.dc-notes a');
    await expect(link).toHaveText('example.com ↗');
    await expect(link).toHaveAttribute('href', 'https://www.example.com/restaurants/tasca-do-chico?ref=a1b2c3d4e5');
    await card.locator('.dc-notes-toggle').click();
    await expect(card.locator('.dc-notes')).toHaveCount(0);
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});

test('a before-the-trip to-do can be renamed in place', async ({ page }) => {
  await signInPage(page, USER, PASS);
  const created = await page.request.post('/api/trips', {
    data: { name: 'E2E planner tasks', start_date: '2027-05-20', end_date: '2027-05-21' },
  });
  const tripId = (await created.json()).id as string;
  try {
    await page.request.post(`/api/trips/${tripId}/plan/tasks`, { data: { text: 'Buy adaptor' } });
    await page.goto(`/#/trips/${tripId}/plan`);
    const box = page.locator('.task .task-text').first();
    await expect(box).toHaveValue('Buy adaptor', { timeout: 15000 });

    await box.fill('Buy travel adaptor');
    await box.press('Enter');
    await expect
      .poll(async () => (await (await page.request.get(`/api/trips/${tripId}/plan`)).json()).tasks[0].text)
      .toBe('Buy travel adaptor');

    // Emptied, it is put back rather than deleted.
    await box.fill('');
    await box.blur();
    await expect(box).toHaveValue('Buy travel adaptor');
  } finally {
    await page.request.delete(`/api/trips/${tripId}`);
  }
});
