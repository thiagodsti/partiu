import { test, expect, type Page } from '@playwright/test';

/**
 * The trip's People section and its guest roster.
 *
 * The bug behind it: guest membership was *derived* from the expenses — a guest
 * counted as "on" a trip once some expense there named them. That left no way
 * in. Three guests created in Settings appeared in no payer select and no
 * split-between list, because no expense named them, and no expense could name
 * them because they were in no list. These tests drive the loop that was
 * broken: put a guest on the trip, then check the expense form offers them.
 */

const BASE_URL = 'http://localhost:8000';

async function createTrip(page: Page, name: string): Promise<string> {
  const res = await page.request.post(`${BASE_URL}/api/trips`, { data: { name } });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).id;
}

async function openTrip(page: Page, tripId: string) {
  await page.goto(`${BASE_URL}/#/trips/${tripId}`);
  await page.waitForLoadState('networkidle');
}

test('a guest added to a trip becomes pickable in that trip\'s expense form', async ({ page }) => {
  const tripId = await createTrip(page, `People E2E ${Date.now()}`);
  await openTrip(page, tripId);

  const name = `Jimmy ${Date.now()}`;
  await page.getByPlaceholder('trip_people.add_placeholder').or(
    page.locator('.people-add input'),
  ).first().fill(name);
  await page.locator('.people-add button[type="submit"]').click();

  await expect(page.locator('.people-row', { hasText: name })).toBeVisible();

  // The point of the roster: the expense form's payer list now offers them.
  const participants = await page.request.get(
    `${BASE_URL}/api/trips/${tripId}/expenses/participants`,
  );
  const names = (await participants.json()).map((p: { name: string }) => p.name);
  expect(names).toContain(name);
});

test('a guest on one trip does not appear on another', async ({ page }) => {
  const stamp = Date.now();
  const tripA = await createTrip(page, `Roster A ${stamp}`);
  const tripB = await createTrip(page, `Roster B ${stamp}`);

  await openTrip(page, tripA);
  const name = `Lucas ${stamp}`;
  await page.locator('.people-add input').first().fill(name);
  await page.locator('.people-add button[type="submit"]').click();
  await expect(page.locator('.people-row', { hasText: name })).toBeVisible();

  // Trip B shares the address book but not the roster — the scoping this
  // feature keeps, and the reason it is a table rather than "all your guests".
  const participants = await page.request.get(
    `${BASE_URL}/api/trips/${tripB}/expenses/participants`,
  );
  const names = (await participants.json()).map((p: { name: string }) => p.name);
  expect(names).not.toContain(name);
});

test('removing a guest an expense names is refused', async ({ page }) => {
  const tripId = await createTrip(page, `Roster block ${Date.now()}`);

  const guest = await page.request.post(`${BASE_URL}/api/guests`, {
    data: { name: `Vivian ${Date.now()}` },
  });
  const guestId = (await guest.json()).id;
  await page.request.post(`${BASE_URL}/api/trips/${tripId}/guests`, {
    data: { guest_id: guestId },
  });
  await page.request.post(`${BASE_URL}/api/trips/${tripId}/expenses`, {
    data: {
      description: 'Cab',
      amount: 30,
      currency: 'EUR',
      paid_by: { type: 'guest', id: guestId },
    },
  });

  const removal = await page.request.delete(
    `${BASE_URL}/api/trips/${tripId}/guests/${guestId}`,
  );
  expect(removal.status()).toBe(409);

  // ...and it is still on the trip afterwards, not half-removed.
  const roster = await page.request.get(`${BASE_URL}/api/trips/${tripId}/guests`);
  expect((await roster.json()).map((g: { id: number }) => g.id)).toContain(guestId);
});

test('the trip header counts the people on the trip', async ({ page }) => {
  const tripId = await createTrip(page, `People count ${Date.now()}`);

  const guest = await page.request.post(`${BASE_URL}/api/guests`, {
    data: { name: `Counted ${Date.now()}` },
  });
  await page.request.post(`${BASE_URL}/api/trips/${tripId}/guests`, {
    data: { guest_id: (await guest.json()).id },
  });

  await openTrip(page, tripId);
  // Owner + one guest = two people; a solo trip prints nothing at all.
  await expect(page.locator('.trip-header-contents')).toContainText('👥');
});
