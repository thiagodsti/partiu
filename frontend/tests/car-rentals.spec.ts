/**
 * E2E tests for car rentals: a hired vehicle held over a span of a trip.
 *
 * The scenarios that matter are the ones the design turns on — that a one-way
 * hire keeps a different zone at each end, that the local dates survive the
 * round trip even when the counter is far enough west that the UTC instant
 * lands on another day, that a rental *extends* the trip's span rather than
 * being validated against it, and that the calendar export gives both counter
 * appointments an alarm while suppressing the all-day band on a same-day hire.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const OWNER_USER = 'e2e_rental_owner';
const OWNER_PASS = 'E2eRentalOwner1!';
const OTHER_USER = 'e2e_rental_other';
const OTHER_PASS = 'E2eRentalOther1!';

const COUNTER_VIENNA = {
  name: 'Vienna Airport',
  address: 'Schwechat Airport, 1300 Vienna',
  lat: 48.1103,
  lon: 16.5697,
  // As the picker supplies it — this is what makes the rental count toward
  // visited countries.
  country_code: 'AT',
};
const COUNTER_MUNICH = { name: 'Munich Airport', lat: 48.3538, lon: 11.7861, country_code: 'DE' };
// UTC-10: an 18:00 drop-off here is 04:00Z the following day.
const COUNTER_HONOLULU = { name: 'Honolulu Airport', lat: 21.3245, lon: -157.9251 };

function rentalPayload(overrides: Record<string, unknown> = {}) {
  return {
    vendor: 'Hertz',
    pickup: COUNTER_VIENNA,
    dropoff: COUNTER_VIENNA,
    pickup_datetime: '2026-03-29T09:30',
    dropoff_datetime: '2026-04-01T23:00',
    booking_reference: 'X11223344Y',
    vehicle: 'Fiat 500 or similar',
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

async function ensureUsers() {
  if (usersResolved) return cachedUsers;
  usersResolved = true;
  cachedUsers = await setUpUsers();
  return cachedUsers;
}

async function setUpUsers() {
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

test('a rental round-trips with local dates and a day count', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E Austria trip');
  const created = await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload(),
  });
  expect(created.status()).toBe(201);

  const rentals = await (await ownerCtx.get(`/api/trips/${tripId}/car-rentals`)).json();
  expect(rentals).toHaveLength(1);

  const rental = rentals[0];
  expect(rental.vendor).toBe('Hertz');
  expect(rental.pickup.name).toBe('Vienna Airport');
  expect(rental.pickup.timezone).toBe('Europe/Vienna');
  expect(rental.pickup_date).toBe('2026-03-29');
  expect(rental.dropoff_date).toBe('2026-04-01');
  expect(rental.days).toBe(3);
  expect(rental.is_one_way).toBe(false);
  expect(rental.vehicle).toBe('Fiat 500 or similar');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a one-way hire keeps a zone at each end', async () => {
  // Two of the three bookings in the measured corpus were one-way, which is why
  // a rental carries two places rather than one.
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E one-way rental');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload({ pickup: COUNTER_MUNICH }),
  });

  const rental = (await (await ownerCtx.get(`/api/trips/${tripId}/car-rentals`)).json())[0];
  expect(rental.is_one_way).toBe(true);
  expect(rental.pickup.timezone).toBe('Europe/Berlin');
  expect(rental.dropoff.timezone).toBe('Europe/Vienna');
  expect(rental.pickup.country_code).toBe('DE');
  expect(rental.dropoff.country_code).toBe('AT');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the local date is read at the counter, not in UTC', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E Hawaii rental');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload({
      pickup: COUNTER_HONOLULU,
      dropoff: COUNTER_HONOLULU,
      pickup_datetime: '2026-03-29T09:00',
      dropoff_datetime: '2026-04-01T18:00',
    }),
  });

  const rental = (await (await ownerCtx.get(`/api/trips/${tripId}/car-rentals`)).json())[0];
  // The instant really is the 2nd in UTC...
  expect(rental.dropoff_datetime).toContain('2026-04-02T04:00:00');
  // ...but the car comes back on the 1st, and that is what the planner bands on.
  expect(rental.dropoff_date).toBe('2026-04-01');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a rental extends the trip span instead of being rejected by it', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E rental span');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, { data: rentalPayload() });

  const trip = await (await ownerCtx.get(`/api/trips/${tripId}`)).json();
  expect(trip.start_date).toBe('2026-03-29');
  expect(trip.end_date).toBe('2026-04-01');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a counter typed by hand is still accepted', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E hand-typed rental');
  const created = await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload({
      pickup: { name: 'A back-street garage' },
      dropoff: { name: 'A back-street garage' },
    }),
  });
  expect(created.status()).toBe(201);

  const rental = (await (await ownerCtx.get(`/api/trips/${tripId}/car-rentals`)).json())[0];
  expect(rental.pickup.lat).toBeNull();
  // No coordinates means no zone to apply, so the time is stored as given, and
  // no country is contributed rather than a guessed one.
  expect(rental.pickup.timezone).toBeNull();
  expect(rental.pickup.country_code).toBeNull();
  expect(rental.pickup_date).toBe('2026-03-29');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('an impossible rental is rejected', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E invalid rental');

  const backwards = await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload({ dropoff_datetime: '2026-03-28T09:00' }),
  });
  expect(backwards.status()).toBe(400);

  // A mistyped year, which is how this usually goes wrong.
  const tooLong = await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload({ dropoff_datetime: '2028-04-01T09:00' }),
  });
  expect(tooLong.status()).toBe(400);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a rental can be edited without losing its untouched fields', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E rental edit');
  const created = await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload(),
  });
  const rentalId = (await created.json()).id;

  const patched = await ownerCtx.patch(`/api/trips/${tripId}/car-rentals/${rentalId}`, {
    data: { vehicle: 'VW Golf' },
  });
  expect(patched.ok()).toBe(true);

  const rental = (await (await ownerCtx.get(`/api/trips/${tripId}/car-rentals`)).json())[0];
  expect(rental.vehicle).toBe('VW Golf');
  expect(rental.booking_reference).toBe('X11223344Y');
  expect(rental.vendor).toBe('Hertz');
  expect(rental.days).toBe(3);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the calendar export gives both counter appointments an alarm', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E rental ical');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, { data: rentalPayload() });

  const res = await ownerCtx.get(`/api/trips/${tripId}/ical`);
  expect(res.ok()).toBe(true);
  const ics = (await res.text()).replace(/\r\n /g, '');

  // Both ends are deadlines — the collection time is binding at most vendors
  // and a late return is charged — so both get an event and an alarm, unlike a
  // stay, where only check-out does.
  expect(ics).toContain('SUMMARY:Pick up car: Hertz');
  expect(ics).toContain('SUMMARY:Return car: Hertz');
  expect(ics).toContain('TRIGGER:-PT1H');

  // The multi-day band, ending the day after the drop-off because DTEND is
  // exclusive on an all-day event.
  expect(ics).toContain('DTSTART;VALUE=DATE:20260329');
  expect(ics).toContain('DTEND;VALUE=DATE:20260402');
  // The address makes the entry tappable into a maps app; its comma is escaped.
  expect(ics).toContain('LOCATION:Schwechat Airport\\, 1300 Vienna');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a same-day hire gets no all-day band', async () => {
  // One of the three measured bookings was collected at 08:00 and returned at
  // 12:30 the same day; an all-day band over a four-hour hire says nothing the
  // two timed events have not already said.
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E same-day rental');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload({
      vendor: 'Europcar',
      pickup_datetime: '2026-03-29T08:00',
      dropoff_datetime: '2026-03-29T12:30',
    }),
  });

  const ics = (await (await ownerCtx.get(`/api/trips/${tripId}/ical`)).text()).replace(/\r\n /g, '');
  expect(ics).toContain('SUMMARY:Pick up car: Europcar');
  expect(ics).toContain('SUMMARY:Return car: Europcar');
  expect(ics).not.toContain('SUMMARY:Europcar: Vienna Airport');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the trips list counts rentals apart from ground legs', async () => {
  // Folding a hire into the leg count would claim a drive that may never have
  // happened, and a rental-only trip must not read "0 flights".
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E rental counts');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, { data: rentalPayload() });

  const list = await (await ownerCtx.get('/api/trips')).json();
  const trip = list.trips.find((t: { id: string }) => t.id === tripId);
  expect(trip.car_rental_count).toBe(1);
  expect(trip.segment_count).toBe(0);
  expect(trip.flight_count).toBe(0);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

/**
 * The only browser-driven case here. It needs the server started with
 * SECURE_COOKIES=false, because the session cookie is `Secure` by default and
 * a browser will not store it over plain http — the API-context tests above are
 * unaffected, which is why the rest of this file asserts through the API.
 */
test('the car rental section and the planner banding render on the trip page', async ({ page }) => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E rental UI');
  await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, { data: rentalPayload() });

  await page.goto(`${BASE}/#/login`);
  await page.waitForLoadState('networkidle');
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
  await expect(page.getByRole('heading', { name: 'Car rental' })).toBeVisible({ timeout: 15000 });

  const row = page.locator('.rental-row', { hasText: 'Hertz' });
  await expect(row).toBeVisible();
  // A return hire prints one place, not "Vienna Airport → Vienna Airport".
  // Asserted on the place line specifically: the window line below it uses an
  // arrow of its own, between the two times.
  await expect(row.locator('.rental-where')).toHaveText('Vienna Airport');
  await expect(row.locator('.rental-window')).toContainText('→');
  await expect(row).toContainText('3 days');

  // The band names the vendor on every day the car is held, including the day
  // it goes back — unlike a stay, whose check-out day is not a night.
  const bands = page.locator('.day-stay-band', { hasText: 'Hertz' });
  await expect(bands.first()).toContainText('day 1 of 4');
  await expect(bands).toHaveCount(4);

  await expect(page.locator('.day-flight-row', { hasText: 'Pick up car' })).toBeVisible();
  await expect(page.locator('.day-flight-row', { hasText: 'Return car' })).toBeVisible();

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test("another user cannot read or write a trip's car rentals", async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping car rental tests');
  const { ownerCtx, otherCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E private rentals');
  const created = await ownerCtx.post(`/api/trips/${tripId}/car-rentals`, {
    data: rentalPayload(),
  });
  const rentalId = (await created.json()).id;

  expect((await otherCtx.get(`/api/trips/${tripId}/car-rentals`)).status()).toBe(404);
  expect(
    (await otherCtx.post(`/api/trips/${tripId}/car-rentals`, { data: rentalPayload() })).status(),
  ).toBe(404);
  expect((await otherCtx.delete(`/api/trips/${tripId}/car-rentals/${rentalId}`)).status()).toBe(404);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});
