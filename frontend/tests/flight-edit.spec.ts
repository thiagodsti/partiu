/**
 * E2E tests for editing a flight — the counterpart to the inline editor ground
 * segments already had.
 *
 * The edit form resubmits every field on save, with the datetimes as naive
 * local time at each airport, so these tests pin the two things that shape
 * makes possible: times are re-localised to UTC (not stored as typed), and a
 * field the user clears is actually cleared.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const OWNER_USER = 'e2e_fedit_owner';
const OWNER_PASS = 'E2eFeditOwner1!';
const OTHER_USER = 'e2e_fedit_other';
const OTHER_PASS = 'E2eFeditOther1!';

function flightPayload(tripId: string, overrides: Record<string, unknown> = {}) {
  return {
    flight_number: 'LA8094',
    airline_code: 'LA',
    airline_name: 'LATAM',
    departure_airport: 'GRU',
    departure_datetime: '2030-06-01T10:00',
    arrival_airport: 'LHR',
    arrival_datetime: '2030-06-01T22:00',
    booking_reference: 'ABC123',
    passenger_name: 'SILVA/JOAO',
    seat: '12A',
    cabin_class: 'economy',
    departure_terminal: '3',
    departure_gate: 'A12',
    arrival_terminal: '2',
    arrival_gate: 'B4',
    notes: 'window seat',
    trip_id: tripId,
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
 * and re-authenticating in every test exhausts that budget partway through. */
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

async function createTripWithFlight(ctx: APIRequestContext, name: string) {
  const trip = await ctx.post('/api/trips', { data: { name } });
  expect(trip.ok()).toBe(true);
  const tripId = (await trip.json()).id;

  const flight = await ctx.post('/api/flights', { data: flightPayload(tripId) });
  expect(flight.status()).toBe(201);
  return { tripId, flightId: (await flight.json()).id };
}

test('the edit form resubmits every field and re-localises the times', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping flight edit tests');
  const { ownerCtx } = users!;

  const { tripId, flightId } = await createTripWithFlight(ownerCtx, 'E2E flight edit');

  // The same payload the form sends on save: all fields, local wall-clock times.
  const patched = await ownerCtx.patch(`/api/flights/${flightId}`, {
    data: {
      flight_number: 'LA8095',
      airline_code: 'LA',
      airline_name: 'LATAM',
      departure_airport: 'GRU',
      departure_datetime: '2030-06-02T09:30',
      arrival_airport: 'LHR',
      arrival_datetime: '2030-06-02T22:00',
      booking_reference: 'ABC123',
      passenger_name: 'SILVA/JOAO',
      seat: '14C',
      cabin_class: 'business',
      departure_terminal: '3',
      departure_gate: 'A12',
      arrival_terminal: '2',
      arrival_gate: '',
      notes: 'aisle seat',
    },
  });
  expect(patched.ok()).toBe(true);

  const flight = await (await ownerCtx.get(`/api/flights/${flightId}`)).json();
  expect(flight.flight_number).toBe('LA8095');
  expect(flight.seat).toBe('14C');
  expect(flight.cabin_class).toBe('business');
  expect(flight.notes).toBe('aisle seat');
  // A field the user cleared in the form is cleared on the flight.
  expect(flight.arrival_gate).toBe('');
  // 09:30 at GRU (UTC-3) is 12:30 UTC; 22:00 at LHR (UTC+1 in June) is 21:00 UTC.
  expect(flight.departure_datetime).toContain('2030-06-02T12:30');
  expect(flight.arrival_datetime).toContain('2030-06-02T21:00');
  expect(flight.duration_minutes).toBe(510);

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test('editing a flight moves the trip span with it', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping flight edit tests');
  const { ownerCtx } = users!;

  const { tripId, flightId } = await createTripWithFlight(ownerCtx, 'E2E flight edit span');

  await ownerCtx.patch(`/api/flights/${flightId}`, {
    data: {
      departure_airport: 'GRU',
      departure_datetime: '2030-07-15T10:00',
      arrival_airport: 'LHR',
      arrival_datetime: '2030-07-15T22:00',
    },
  });

  const trip = await (await ownerCtx.get(`/api/trips/${tripId}`)).json();
  expect(trip.start_date).toContain('2030-07-15');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});

test("another user cannot edit someone else's flight", async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up users — skipping flight edit tests');
  const { ownerCtx, otherCtx } = users!;

  const { tripId, flightId } = await createTripWithFlight(ownerCtx, 'E2E flight edit perms');

  const res = await otherCtx.patch(`/api/flights/${flightId}`, { data: { seat: '1A' } });
  expect(res.status()).toBe(404);

  const flight = await (await ownerCtx.get(`/api/flights/${flightId}`)).json();
  expect(flight.seat).toBe('12A');

  await ownerCtx.delete(`/api/trips/${tripId}`);
});
