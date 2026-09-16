/**
 * E2E tests for cancellations reaching flights that are already stored.
 *
 * Every parser in the package refuses to *create* a cancelled leg, and until
 * `_apply_cancellations` existed nothing ever went back to the leg the booking
 * confirmation had created weeks earlier. This file drives that through the one
 * user-facing flow that runs the whole pipeline against a live server —
 * POST /api/sync/upload-eml — by storing a flight first and then uploading the
 * airline's cancellation notice.
 *
 * The case worth having here is `a schedule change is not a cancellation`: SAS's
 * schedule-change mail carries the same booking reference and the words "cancel
 * your booking", offered as one of three options, and it reprints no itinerary —
 * so reading it as a cancellation would strike off a trip that is still going
 * ahead, with nothing left to put it back.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const USER = 'e2e_cancel_user';
const PASS = 'E2eCancelUser1!';

async function loginContext(): Promise<APIRequestContext | null> {
  const ctx = await request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username: USER, password: PASS } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

let cachedCtx: APIRequestContext | null = null;
let resolved = false;

/** Cached: logins are rate-limited to 5/min per IP, and re-authenticating in
 * every test exhausts that budget partway through the file. */
async function ensureUser(): Promise<APIRequestContext | null> {
  if (resolved) return cachedCtx;
  resolved = true;
  const anon = await request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: USER, password: PASS },
  });
  await anon.dispose();
  if (setupRes.ok() || setupRes.status() === 409) cachedCtx = await loginContext();
  return cachedCtx;
}

function buildEml(opts: { from: string; subject: string; date: string; text: string }): Buffer {
  return Buffer.from(
    [
      `From: ${opts.from}`,
      'To: traveller@example.com',
      `Subject: ${opts.subject}`,
      `Date: ${opts.date}`,
      `Message-ID: <e2e-cancel-${Math.random().toString(36).slice(2)}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset="utf-8"',
      '',
      opts.text,
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

async function uploadEml(ctx: APIRequestContext, name: string, buffer: Buffer) {
  return ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name, mimeType: 'message/rfc822', buffer } },
  });
}

/** A flight the traveller already has, as a booking confirmation would leave it. */
async function storeFlight(
  ctx: APIRequestContext,
  tripId: string,
  opts: { number: string; ref: string; dep: string; arr: string },
) {
  const res = await ctx.post('/api/flights', {
    data: {
      trip_id: tripId,
      flight_number: opts.number,
      booking_reference: opts.ref,
      departure_airport: 'ARN',
      arrival_airport: 'CPH',
      departure_datetime: opts.dep,
      arrival_datetime: opts.arr,
    },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).id as string;
}

async function statusOf(ctx: APIRequestContext, flightId: string): Promise<string> {
  const res = await ctx.get(`/api/flights/${flightId}`);
  expect(res.ok()).toBeTruthy();
  return (await res.json()).status;
}

function uniqueRef(prefix: string): string {
  // Booking references must not collide between runs of this spec, or an
  // earlier run's flights would be cancelled by this one's upload.
  return (prefix + Math.random().toString(36).slice(2).toUpperCase()).slice(0, 6);
}

test('a SAS cancellation strikes off every leg under its booking reference', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping cancellation tests');

  const tripId = (await (await ctx!.post('/api/trips', { data: { name: 'E2E cancel SAS' } })).json())
    .id;
  const ref = uniqueRef('QQ');
  const otherRef = uniqueRef('ZZ');

  const outbound = await storeFlight(ctx!, tripId, {
    number: 'SK1401',
    ref,
    dep: '2027-06-01T08:00',
    arr: '2027-06-01T09:20',
  });
  const back = await storeFlight(ctx!, tripId, {
    number: 'SK1408',
    ref,
    dep: '2027-06-05T18:00',
    arr: '2027-06-05T19:20',
  });
  const untouched = await storeFlight(ctx!, tripId, {
    number: 'SK1500',
    ref: otherRef,
    dep: '2027-07-01T08:00',
    arr: '2027-07-01T09:20',
  });

  const res = await uploadEml(
    ctx!,
    'sas-cancellation.eml',
    buildEml({
      from: 'SAS <no-reply@flysas.com>',
      subject: 'Cancellation Confirmation',
      date: 'Mon, 10 May 2027 12:00:00 +0000',
      text: `Dear Traveler,\r\n\r\nYou have now cancelled your trip.\r\n\r\nBooking reference:  ${ref}\r\n\r\nSAS will make the refund instantly.\r\n`,
    }),
  );
  expect(res.ok()).toBeTruthy();
  expect((await res.json()).flights_cancelled).toBe(2);

  expect(await statusOf(ctx!, outbound)).toBe('cancelled');
  expect(await statusOf(ctx!, back)).toBe('cancelled');
  // A different booking is untouched.
  expect(await statusOf(ctx!, untouched)).not.toBe('cancelled');

  await ctx!.delete(`/api/trips/${tripId}`);
});

test('an Austrian cancellation strikes off one leg, not its sibling', async () => {
  // Austrian cancels a single flight. The same reference holds the return leg,
  // which the mail says nothing about — it is explicitly about finding an
  // alternative for *this* flight.
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping cancellation tests');

  const tripId = (await (await ctx!.post('/api/trips', { data: { name: 'E2E cancel OS' } })).json())
    .id;
  const ref = uniqueRef('OS');

  const outbound = await storeFlight(ctx!, tripId, {
    number: 'OS318',
    ref,
    dep: '2027-03-29T08:00',
    arr: '2027-03-29T10:20',
  });
  const back = await storeFlight(ctx!, tripId, {
    number: 'OS319',
    ref,
    dep: '2027-04-02T18:00',
    arr: '2027-04-02T20:20',
  });

  const res = await uploadEml(
    ctx!,
    'austrian-cancellation.eml',
    buildEml({
      from: 'Austrian.com <no-reply@notifications.austrian.com>',
      subject: 'Cancellation of your flight OS318 Stockholm - Vienna on 29.3.2027',
      date: 'Fri, 26 Mar 2027 17:26:00 +0000',
      text: 'Your Austrian flight OS318 from Stockholm to Vienna on 29.3.2027 has been cancelled.\r\nPlease accept our sincere apologies.\r\n',
    }),
  );
  expect(res.ok()).toBeTruthy();
  expect((await res.json()).flights_cancelled).toBe(1);

  expect(await statusOf(ctx!, outbound)).toBe('cancelled');
  expect(await statusOf(ctx!, back)).not.toBe('cancelled');

  await ctx!.delete(`/api/trips/${tripId}`);
});

test('a schedule change is not a cancellation', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping cancellation tests');

  const tripId = (await (
    await ctx!.post('/api/trips', { data: { name: 'E2E schedule change' } })
  ).json()).id;
  const ref = uniqueRef('SC');

  const flightId = await storeFlight(ctx!, tripId, {
    number: 'SK1601',
    ref,
    dep: '2027-08-01T08:00',
    arr: '2027-08-01T09:20',
  });

  const res = await uploadEml(
    ctx!,
    'sas-schedule-change.eml',
    buildEml({
      from: 'SAS <no-reply@msg.flysas.com>',
      subject: `Schedule change from SAS - Booking reference ${ref}`,
      date: 'Sat, 1 May 2027 12:00:00 +0000',
      text: `Important information about your SAS booking ${ref}\r\n\r\nUnfortunately, we've had to change our flight schedule which has impacted your trip with booking reference ${ref}.\r\nPlease see our suggested new itinerary in My Bookings.\r\n\r\nYou now have three options:\r\nTravel on the new flight(s) we provide as an alternative\r\nRebook to a new flight, free of charge\r\nCancel your booking\r\nIf you choose not to travel, you can cancel your booking and get a refund.\r\n`,
    }),
  );
  expect(res.ok()).toBeTruthy();
  expect((await res.json()).flights_cancelled).toBe(0);

  expect(await statusOf(ctx!, flightId)).not.toBe('cancelled');

  await ctx!.delete(`/api/trips/${tripId}`);
});

test('a cancelled flight stops counting toward the travel statistics', async () => {
  // The point of marking rather than deleting is that the row stays readable —
  // but a flight that did not happen must not contribute its distance, its CO2
  // or its countries.
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping cancellation tests');

  const tripId = (await (await ctx!.post('/api/trips', { data: { name: 'E2E cancel stats' } })).json())
    .id;
  const ref = uniqueRef('ST');

  // In the past, so it counts as a completed flight until it is cancelled.
  await storeFlight(ctx!, tripId, {
    number: 'SK1701',
    ref,
    dep: '2021-06-01T08:00',
    arr: '2021-06-01T09:20',
  });

  const before = await (await ctx!.get('/api/stats?year=2021')).json();

  await uploadEml(
    ctx!,
    'sas-cancellation-stats.eml',
    buildEml({
      from: 'SAS <message@sas.se>',
      subject: 'Cancellation Confirmation',
      date: 'Mon, 10 May 2021 12:00:00 +0000',
      text: `Dear Traveler,\r\n\r\nYou have now cancelled your trip.\r\n\r\nBooking reference:  ${ref}\r\n\r\n`,
    }),
  );

  const after = await (await ctx!.get('/api/stats?year=2021')).json();
  expect(after.total_flights).toBe(before.total_flights - 1);

  await ctx!.delete(`/api/trips/${tripId}`);
});
