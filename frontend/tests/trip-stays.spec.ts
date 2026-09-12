/**
 * E2E tests for stays: hotels, Airbnbs and hostels booked on a trip.
 *
 * The scenarios that matter here are the ones the design turns on — that a
 * booking's local dates survive the round trip even when the property is far
 * enough west that the UTC instant lands on a different day, that a stay
 * *extends* the trip's span instead of being validated against it, and that the
 * calendar export puts the nights in one all-day block ending after check-out.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const OWNER_USER = 'e2e_stay_owner';
const OWNER_PASS = 'E2eStayOwner1!';
const OTHER_USER = 'e2e_stay_other';
const OTHER_PASS = 'E2eStayOther1!';

const HOTEL_LISBON = {
  name: 'Hotel Avenida Palace',
  address: 'R. 1º de Dezembro 123, 1200-359 Lisboa',
  lat: 38.7145,
  lon: -9.1409,
  // As the picker supplies it — this is what makes the stay count toward
  // visited countries.
  country_code: 'PT',
};
// UTC-10: a 15:00 check-in here is 01:00Z the following day.
const HOTEL_HONOLULU = { name: 'Waikiki Beach Hotel', lat: 21.2793, lon: -157.8292 };

function stayPayload(overrides: Record<string, unknown> = {}) {
  return {
    kind: 'hotel',
    place: HOTEL_LISBON,
    check_in_datetime: '2026-10-04T15:00',
    check_out_datetime: '2026-10-08T11:00',
    booking_reference: 'BK12345',
    guests: 2,
    ...overrides,
  };
}

async function loginContext(username: string, password: string): Promise<APIRequestContext | null> {
  const ctx = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username, password } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

/** Cached across tests in this file: logins are rate-limited to 5/min per IP,
 * and re-authenticating in every test exhausts that budget partway through the
 * file, silently skipping the remaining cases. */
let cachedUsers: { ownerCtx: APIRequestContext; otherCtx: APIRequestContext } | null = null;
let usersResolved = false;

async function ensureUsers(): Promise<{ ownerCtx: APIRequestContext; otherCtx: APIRequestContext } | null> {
  if (usersResolved) return cachedUsers;
  usersResolved = true;
  cachedUsers = await setUpUsers();
  return cachedUsers;
}

async function setUpUsers(): Promise<{ ownerCtx: APIRequestContext; otherCtx: APIRequestContext } | null> {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: OWNER_USER, password: OWNER_PASS, smtp_recipient_address: '' },
  });
  await anon.dispose();

  if (!setupRes.ok() && setupRes.status() !== 409) return null;
  const ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  if (!ownerCtx) return null;

  await ownerCtx.post('/api/users', {
    data: { username: OTHER_USER, password: OTHER_PASS, is_admin: false },
  });
  const otherCtx = await loginContext(OTHER_USER, OTHER_PASS);
  if (!otherCtx) return null;

  return { ownerCtx, otherCtx };
}

async function createTrip(ctx: APIRequestContext, name: string): Promise<string> {
  const res = await ctx.post('/api/trips', { data: { name } });
  expect(res.ok()).toBe(true);
  return (await res.json()).id;
}

test('a hotel stay round-trips with local dates and a night count', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E Portugal trip');

  const created = await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });
  expect(created.status()).toBe(201);

  const stays = await (await ownerCtx.get(`/api/trips/${tripId}/stays`)).json();
  expect(stays).toHaveLength(1);

  const stay = stays[0];
  expect(stay.kind).toBe('hotel');
  expect(stay.place.name).toBe(HOTEL_LISBON.name);
  expect(stay.place.timezone).toBe('Europe/Lisbon');
  expect(stay.check_in_date).toBe('2026-10-04');
  expect(stay.check_out_date).toBe('2026-10-08');
  expect(stay.nights).toBe(4);
  expect(stay.guests).toBe(2);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the local date is read at the property, not in UTC', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E Hawaii trip');
  await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({
      place: HOTEL_HONOLULU,
      check_in_datetime: '2026-10-04T15:00',
      check_out_datetime: '2026-10-06T11:00',
    }),
  });

  const stay = (await (await ownerCtx.get(`/api/trips/${tripId}/stays`)).json())[0];
  // The instant really is the 5th in UTC...
  expect(stay.check_in_datetime).toContain('2026-10-05T01:00:00');
  // ...but the booking is for the 4th, and that is what the planner bands on.
  expect(stay.check_in_date).toBe('2026-10-04');
  expect(stay.nights).toBe(2);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a stay extends the trip span instead of being rejected by it', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E span trip');
  await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });

  // The airport hotel the night before an early departure: outside the span the
  // first stay established, and a real booking.
  const early = await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({
      place: { name: 'Airport Inn' },
      check_in_datetime: '2026-10-01T22:00',
      check_out_datetime: '2026-10-02T06:00',
    }),
  });
  expect(early.status()).toBe(201);

  const trip = await (await ownerCtx.get(`/api/trips/${tripId}`)).json();
  expect(trip.start_date).toBe('2026-10-01');
  expect(trip.end_date).toBe('2026-10-08');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('an Airbnb with no coordinates is still accepted', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E airbnb trip');
  const created = await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({ kind: 'airbnb', place: { name: 'Flat in Alfama' } }),
  });
  expect(created.status()).toBe(201);

  const stay = (await (await ownerCtx.get(`/api/trips/${tripId}/stays`)).json())[0];
  expect(stay.place.lat).toBeNull();
  // No coordinates means no zone to apply, so the time is stored as given.
  expect(stay.place.timezone).toBeNull();
  expect(stay.check_in_date).toBe('2026-10-04');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('an impossible stay is rejected', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E invalid stay');

  const backwards = await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({ check_out_datetime: '2026-10-01T11:00' }),
  });
  expect(backwards.status()).toBe(400);

  // A mistyped year, which is how this usually goes wrong.
  const tooLong = await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({ check_out_datetime: '2028-10-08T11:00' }),
  });
  expect(tooLong.status()).toBe(400);

  const badKind = await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({ kind: 'castle' }),
  });
  expect(badKind.status()).toBe(400);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a stay can be edited without losing its untouched fields', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E stay edit');
  const created = await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });
  const stayId = (await created.json()).id;

  const patched = await ownerCtx.patch(`/api/trips/${tripId}/stays/${stayId}`, {
    data: { room_type: 'Double, sea view' },
  });
  expect(patched.ok()).toBe(true);

  const stay = (await (await ownerCtx.get(`/api/trips/${tripId}/stays`)).json())[0];
  expect(stay.room_type).toBe('Double, sea view');
  expect(stay.booking_reference).toBe('BK12345');
  expect(stay.nights).toBe(4);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the calendar export carries the stay as an all-day block plus a checkout reminder', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E stay ical');
  await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });

  const res = await ownerCtx.get(`/api/trips/${tripId}/ical`);
  expect(res.ok()).toBe(true);
  const ics = (await res.text()).replace(/\r\n /g, '');

  expect(ics).toContain('DTSTART;VALUE=DATE:20261004');
  // DTEND is exclusive, so a 4-8 October booking ends on the 9th — otherwise the
  // block stops before the morning the guest is still there.
  expect(ics).toContain('DTEND;VALUE=DATE:20261009');
  expect(ics).toContain('SUMMARY:Hotel Avenida Palace');
  expect(ics).toContain('SUMMARY:Check out: Hotel Avenida Palace');
  expect(ics).toContain('TRIGGER:-PT1H');
  // The address makes the entry tappable into a maps app; its comma is escaped.
  expect(ics).toContain('LOCATION:R. 1º de Dezembro 123\\, 1200-359 Lisboa');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

/**
 * The only browser-driven case here. It needs the server started with
 * SECURE_COOKIES=false, because the session cookie is `Secure` by default and
 * a browser will not store it over plain http — the API-context tests above are
 * unaffected, which is why the rest of this file asserts through the API.
 */
test('the stays section and the planner banding render on the trip page', async ({ page }) => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E stays UI');
  await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });

  await page.goto(`${BASE}/#/login`);
  await page.waitForLoadState('networkidle');
  // The app renders the trips list directly when a session cookie is already
  // present, so the login form is only filled in when it actually appears —
  // waited for explicitly, because a bare count() does not auto-wait and would
  // race the app's first render.
  const usernameField = page.locator('#login-username');
  const loginShown = await usernameField
    .waitFor({ state: 'visible', timeout: 10000 })
    .then(() => true)
    .catch(() => false);
  if (loginShown) {
    await usernameField.fill(OWNER_USER);
    await page.locator('#login-password').fill(OWNER_PASS);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/auth/login')),
      page.click('button[type="submit"]'),
    ]);
    await page.waitForLoadState('networkidle');
  }

  const sessionCookie = (await page.context().cookies()).find((c) => c.name === 'session');
  test.skip(!sessionCookie, 'Browser could not hold a session — run the server with SECURE_COOKIES=false');

  await page.goto(`${BASE}/#/trips/${tripId}`);
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('heading', { name: 'Stays' })).toBeVisible({ timeout: 15000 });

  const stayRow = page.locator('.stay-row', { hasText: 'Hotel Avenida Palace' });
  await expect(stayRow).toBeVisible();
  await expect(stayRow).toContainText('4 nights');

  // The band names the property on every night it covers, without the card
  // having to be expanded. The 4th is the first of four nights.
  const bands = page.locator('.day-stay-band', { hasText: 'Hotel Avenida Palace' });
  await expect(bands.first()).toContainText('night 1 of 4');
  // Four nights banded (the 4th to the 7th); the 8th is a check-out, not a night.
  await expect(bands).toHaveCount(4);

  // Check-in and check-out are entries on their own days, alongside any flights.
  await expect(page.locator('.day-flight-row', { hasText: 'Check-in' })).toBeVisible();
  await expect(page.locator('.day-flight-row', { hasText: 'Check-out' })).toBeVisible();

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a stay records the country the picker resolved', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E stay country');
  await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });

  const stay = (await (await ownerCtx.get(`/api/trips/${tripId}/stays`)).json())[0];
  expect(stay.place.country_code).toBe('PT');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a hand-typed stay gets no country rather than a guessed one', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E stay no country');
  await ownerCtx.post(`/api/trips/${tripId}/stays`, {
    data: stayPayload({ kind: 'airbnb', place: { name: "Ana's flat" } }),
  });

  const stay = (await (await ownerCtx.get(`/api/trips/${tripId}/stays`)).json())[0];
  expect(stay.place.country_code).toBeNull();

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the place search returns accommodation and addresses', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx } = users!;

  const res = await ownerCtx.get('/api/places/search?q=Hotel%20Avenida%20Palace%20Lisboa');
  expect(res.ok()).toBe(true);
  const results = await res.json();
  // Photon is optional, so an empty result set is a legitimate outcome here;
  // what must hold is the shape when it does answer.
  test.skip(results.length === 0, 'Geocoder unavailable — skipping place-search assertions');

  expect(results[0]).toHaveProperty('category');
  expect(results[0]).toHaveProperty('address');
  expect(results[0].countrycode).toBe('PT');
});

test("another user cannot read or write a trip's stays", async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping stays tests');
  const { ownerCtx, otherCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E private stays');
  const created = await ownerCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() });
  const stayId = (await created.json()).id;

  expect((await otherCtx.get(`/api/trips/${tripId}/stays`)).status()).toBe(404);
  expect(
    (await otherCtx.post(`/api/trips/${tripId}/stays`, { data: stayPayload() })).status(),
  ).toBe(404);
  expect((await otherCtx.delete(`/api/trips/${tripId}/stays/${stayId}`)).status()).toBe(404);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});
