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

/* The bug this pins: the People section and the expense form are different
 * cards on the same page, and adding a guest updated only the first. The
 * guest was on the trip server-side, but its payer select and split-between
 * picker had loaded their list on mount and never looked again — so the guest
 * you had just added could not be used until a hard refresh. */
test('a guest added to the trip appears in the expense form without reloading', async ({ page }) => {
  const tripId = await createTrip(page, `Picker refresh ${Date.now()}`);
  await openTrip(page, tripId);

  // Open the expense form first, so the pickers are mounted with the old list.
  await page.locator('.expenses-add-btn').click();
  await expect(page.locator('.expense-add-form')).toBeVisible();

  const name = `Vivian ${Date.now()}`;
  await page.locator('.people-add input').first().fill(name);
  await page.locator('.people-add button[type="submit"]').click();
  await expect(page.locator('.people-row', { hasText: name })).toBeVisible();

  // No navigation, no reload: the same page must now offer them.
  await expect(page.locator('#new-paid-by option', { hasText: name })).toHaveCount(1);
});

/* Typing a name you have used before means *that* person. The form used to
 * create a second guest every time, so a trip's payer select ended up with two
 * identical names and one person's expense history split across two ids. */
test('typing a name already in the address book reuses that guest', async ({ page }) => {
  const stamp = Date.now();
  const name = `Jimmy ${stamp}`;
  const first = await page.request.post(`${BASE_URL}/api/guests`, { data: { name } });
  const guestId = (await first.json()).id;

  // Different case, same person — the match is folded, like the picker's search.
  const again = await page.request.post(`${BASE_URL}/api/guests`, {
    data: { name: name.toUpperCase() },
  });
  const body = await again.json();
  expect(body.id).toBe(guestId);
  expect(body.created).toBe(false);
  expect(body.name).toBe(name);

  const book = await page.request.get(`${BASE_URL}/api/guests`);
  const matches = (await book.json()).filter((g: { name: string }) => g.name === name);
  expect(matches).toHaveLength(1);
});

test('the add box suggests a guest you have travelled with before', async ({ page }) => {
  const stamp = Date.now();
  const name = `Lucas ${stamp}`;
  await page.request.post(`${BASE_URL}/api/guests`, { data: { name } });

  const tripId = await createTrip(page, `Suggest ${stamp}`);
  await openTrip(page, tripId);

  await page.locator('.people-add input').first().fill(`lucas ${stamp}`);
  const suggestion = page.locator('.people-suggestion', { hasText: name });
  await expect(suggestion).toBeVisible();
  await suggestion.click();

  await expect(page.locator('.people-row', { hasText: name })).toBeVisible();
  // Picked, not re-created: the address book still holds exactly one Lucas.
  const book = await page.request.get(`${BASE_URL}/api/guests`);
  const matches = (await book.json()).filter((g: { name: string }) => g.name === name);
  expect(matches).toHaveLength(1);
});

test('deleting a guest who is on a trip is refused until it is confirmed', async ({ page }) => {
  const stamp = Date.now();
  const tripId = await createTrip(page, `Cascade ${stamp}`);
  const guest = await page.request.post(`${BASE_URL}/api/guests`, {
    data: { name: `Vivian ${stamp}` },
  });
  const guestId = (await guest.json()).id;
  await page.request.post(`${BASE_URL}/api/trips/${tripId}/guests`, {
    data: { guest_id: guestId },
  });

  // The delete cascades their roster rows away, so it names the trips first.
  const refused = await page.request.delete(`${BASE_URL}/api/guests/${guestId}`);
  expect(refused.status()).toBe(409);
  const detail = (await refused.json()).detail;
  expect(detail.error).toBe('guest_on_trips');
  expect(detail.params.trips).toContain(`Cascade ${stamp}`);

  const stillThere = await page.request.get(`${BASE_URL}/api/trips/${tripId}/guests`);
  expect((await stillThere.json()).map((g: { id: number }) => g.id)).toContain(guestId);

  const forced = await page.request.delete(`${BASE_URL}/api/guests/${guestId}?force=true`);
  expect(forced.status()).toBe(204);
  const roster = await page.request.get(`${BASE_URL}/api/trips/${tripId}/guests`);
  expect(await roster.json()).toEqual([]);
});
