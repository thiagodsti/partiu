/**
 * E2E tests for ground transport segments: manually-added train/bus/ferry/car
 * legs on a trip.
 *
 * Mirrors the scenario the feature was designed around — a China trip whose
 * flights land at PEK, with a G87 high-speed train from Beijing West to Xi'an
 * North in between. The times sent are local at each station; the API is
 * expected to store UTC, which is what makes the duration honest.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const OWNER_USER = 'e2e_seg_owner';
const OWNER_PASS = 'E2eSegOwner1!';
const OTHER_USER = 'e2e_seg_other';
const OTHER_PASS = 'E2eSegOther1!';

const BEIJING_WEST = {
  name: 'Beijing West Railway Station',
  lat: 39.8936695,
  lon: 116.3151027,
};
const XIAN_NORTH = {
  name: "Xi'an North Railway Station",
  lat: 34.3775583,
  lon: 108.9339348,
};

function trainPayload(overrides: Record<string, unknown> = {}) {
  return {
    type: 'train',
    operator: 'China Railway',
    number: 'G87',
    departure: BEIJING_WEST,
    arrival: XIAN_NORTH,
    departure_datetime: '2026-10-04T08:00',
    arrival_datetime: '2026-10-04T12:30',
    seat: 'Car 3, 12A',
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

test('a train segment round-trips with local times converted to UTC', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E China trip');

  const created = await ownerCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() });
  expect(created.status()).toBe(201);

  const list = await ownerCtx.get(`/api/trips/${tripId}/segments`);
  expect(list.ok()).toBe(true);
  const segments = await list.json();
  expect(segments).toHaveLength(1);

  const segment = segments[0];
  expect(segment.type).toBe('train');
  expect(segment.operator).toBe('China Railway');
  expect(segment.number).toBe('G87');
  expect(segment.departure.name).toBe(BEIJING_WEST.name);
  // 08:00 at Beijing West is 00:00 UTC — resolved from the station's coordinates.
  expect(segment.departure.timezone).toBe('Asia/Shanghai');
  expect(segment.departure_datetime).toContain('2026-10-04T00:00:00');
  expect(segment.duration_minutes).toBe(270);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a segment can be edited without losing its untouched fields', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E segment edit');
  const created = await ownerCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() });
  const segmentId = (await created.json()).id;

  const patched = await ownerCtx.patch(`/api/trips/${tripId}/segments/${segmentId}`, {
    data: { seat: 'Car 8, 4F' },
  });
  expect(patched.ok()).toBe(true);

  const segment = (await (await ownerCtx.get(`/api/trips/${tripId}/segments`)).json())[0];
  expect(segment.seat).toBe('Car 8, 4F');
  expect(segment.operator).toBe('China Railway');
  expect(segment.number).toBe('G87');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a hand-typed place with no coordinates is still accepted', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E freetext segment');
  const created = await ownerCtx.post(`/api/trips/${tripId}/segments`, {
    data: trainPayload({
      type: 'bus',
      departure: { name: 'Village bus stop' },
      arrival: { name: 'Another village' },
    }),
  });
  expect(created.status()).toBe(201);

  const segment = (await (await ownerCtx.get(`/api/trips/${tripId}/segments`)).json())[0];
  expect(segment.departure.lat).toBeNull();
  // No coordinates means no zone to apply, so the time is stored as given.
  expect(segment.departure.timezone).toBeNull();

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('an implausible segment is rejected', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E invalid segment');

  const backwards = await ownerCtx.post(`/api/trips/${tripId}/segments`, {
    data: trainPayload({ arrival_datetime: '2026-10-04T07:00' }),
  });
  expect(backwards.status()).toBe(400);

  const badType = await ownerCtx.post(`/api/trips/${tripId}/segments`, {
    data: trainPayload({ type: 'teleport' }),
  });
  expect(badType.status()).toBe(400);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test("another user cannot read or write a trip's segments", async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx, otherCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E private segments');
  await ownerCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() });

  expect((await otherCtx.get(`/api/trips/${tripId}/segments`)).status()).toBe(404);
  expect(
    (await otherCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() })).status(),
  ).toBe(404);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the station search endpoint requires authentication', async () => {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const res = await anon.get('/api/stations/search?q=beijing');
  expect(res.status()).toBe(401);
  await anon.dispose();
});

test("a segment extends the trip's date range past its last flight", async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E span');
  await ownerCtx.post('/api/flights', {
    data: {
      trip_id: tripId,
      flight_number: 'LH722',
      departure_airport: 'FRA',
      arrival_airport: 'PEK',
      departure_datetime: '2026-10-03T13:40',
      arrival_datetime: '2026-10-04T06:20',
    },
  });

  // Oct 3, not Oct 4: the span is computed from DATE() of the stored UTC
  // instants, and a 06:20 Beijing arrival is 22:20Z the previous day. That
  // predates segments — it is flights' existing behaviour, matched here rather
  // than changed.
  const beforeSegment = await (await ownerCtx.get(`/api/trips/${tripId}`)).json();
  expect(beforeSegment.end_date).toBe('2026-10-03');

  // A bus on the 5th: without the span covering it, the day planner renders no
  // card for that day and the leg is invisible.
  await ownerCtx.post(`/api/trips/${tripId}/segments`, {
    data: trainPayload({
      type: 'bus',
      departure_datetime: '2026-10-05T09:15',
      arrival_datetime: '2026-10-05T10:30',
    }),
  });

  const afterSegment = await (await ownerCtx.get(`/api/trips/${tripId}`)).json();
  expect(afterSegment.start_date).toBe('2026-10-03');
  expect(afterSegment.end_date).toBe('2026-10-05');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

/**
 * The only browser-driven case here. It needs the server started with
 * SECURE_COOKIES=false, because the session cookie is `Secure` by default and
 * a browser will not store it over plain http — the API-context tests above are
 * unaffected, which is why the rest of this file (and the other specs) assert
 * through the API.
 */
test('the ground transport section renders on the trip page', async ({ page }) => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E segments UI');
  await ownerCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() });

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
  await expect(page.getByRole('heading', { name: 'Transport' })).toBeVisible({ timeout: 15000 });

  // The ground leg renders as a row in the same list as the flights, not in a
  // section of its own.
  const segmentRow = page.locator('.segment-row-btn', { hasText: 'China Railway G87' });
  await expect(segmentRow).toBeVisible();
  await expect(segmentRow).toContainText(BEIJING_WEST.name);
  await expect(segmentRow).toContainText('08:00');

  // The same leg must also reach the day planner's card for the day it departs.
  const dayRow = page.locator('.day-flight-row', { hasText: 'China Railway G87' });
  await expect(dayRow).toBeVisible();
  await expect(dayRow).toContainText(BEIJING_WEST.name);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('a round trip groups its legs into outbound, getting around, and return', async ({ page }) => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E buckets');
  for (const f of [
    {
      flight_number: 'LH722',
      departure_airport: 'FRA',
      arrival_airport: 'PEK',
      departure_datetime: '2026-10-01T13:40',
      arrival_datetime: '2026-10-02T06:20',
    },
    {
      flight_number: 'LH723',
      departure_airport: 'PEK',
      arrival_airport: 'FRA',
      departure_datetime: '2026-10-14T09:00',
      arrival_datetime: '2026-10-14T13:30',
    },
  ]) {
    await ownerCtx.post('/api/flights', { data: { trip_id: tripId, ...f } });
  }
  await ownerCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() });

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
  await expect(page.getByRole('heading', { name: 'Transport' })).toBeVisible({ timeout: 15000 });

  // Three dividers in order, with the train in the middle one. The round trip
  // splitting at all is the point: its origin and destination are both FRA.
  const dividers = page.locator('.section-divider-label');
  await expect(dividers).toHaveCount(3);
  await expect(dividers.nth(0)).toContainText(/outbound/i);
  await expect(dividers.nth(1)).toContainText(/getting around/i);
  await expect(dividers.nth(2)).toContainText(/return/i);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('the calendar export includes ground legs and planner days', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping segments tests');
  const { ownerCtx } = users!;

  const tripId = await createTrip(ownerCtx, 'E2E ical');
  await ownerCtx.post(`/api/trips/${tripId}/segments`, { data: trainPayload() });
  await ownerCtx.patch(`/api/trips/${tripId}/day-notes/2026-10-05`, {
    data: {
      content: JSON.stringify({
        note: 'Terracotta Army, then the Muslim Quarter',
        items: [{ text: 'Buy museum tickets', checked: false }],
      }),
    },
  });

  const res = await ownerCtx.get(`/api/trips/${tripId}/ical`);
  expect(res.ok()).toBe(true);
  const raw = await res.text();
  // Unfold before matching: RFC 5545 splits content lines at 75 octets.
  const ics = raw.replace(/\r\n /g, '');

  expect(ics).toContain('China Railway G87');
  expect(ics).toContain('Beijing West Railway Station');
  expect(ics).toContain('TRIGGER:-PT1H');

  // Planner days have no time of their own, so they export as all-day events —
  // DTEND is the *next* day, since all-day DTEND is exclusive.
  expect(ics).toContain('DTSTART;VALUE=DATE:20261005');
  expect(ics).toContain('DTEND;VALUE=DATE:20261006');
  expect(ics).toContain('☐ Buy museum tickets');
  // Commas inside a note must be escaped or they split the TEXT field.
  expect(ics).toContain('Terracotta Army\\, then the Muslim Quarter');

  // No content line may exceed 75 octets.
  const longest = Math.max(...raw.split('\r\n').map((l) => Buffer.byteLength(l, 'utf8')));
  expect(longest).toBeLessThanOrEqual(75);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});
