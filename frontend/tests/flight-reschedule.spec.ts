/**
 * E2E tests for schedule changes reaching flights that are already stored.
 *
 * A change mail that reprints the itinerary has always overwritten the stored
 * leg's times through "newer email wins" — silently. These drive the whole
 * pipeline through POST /api/sync/upload-eml and check what is now recorded:
 * the previous times on the row, a leg moved to another day landing on the
 * *same* row instead of beside it, and SAS's itinerary-less notice flagging the
 * booking.
 *
 * The receipts are GDS compact-layout tickets written with bare IATA codes, so
 * they parse on any install regardless of which airline rules and airports are
 * present.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';

// Overridable so the spec can be pointed at a throwaway server on another port.
const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:8000';
const USER = 'e2e_resched_user';
const PASS = 'E2eReschedUser1!';

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

/** Cached: logins are rate-limited to 5/min per IP. */
async function ensureUser(): Promise<APIRequestContext | null> {
  if (resolved) return cachedCtx;
  resolved = true;
  const anon = await request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', { data: { username: USER, password: PASS } });
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
      `Message-ID: <e2e-resched-${Math.random().toString(36).slice(2)}@example.com>`,
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
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name, mimeType: 'message/rfc822', buffer } },
  });
  expect(res.ok()).toBeTruthy();
  return res;
}

/** A compact-layout ticket receipt: legs like "TP 783 / 10NOV ARN - LIS 19:05 22:35". */
function receipt(ref: string, legs: string[]): string {
  return ['ELECTRONIC TICKET RECEIPT', `BOOKING REF: ${ref}`, ...legs, ''].join('\n');
}

async function flightsFor(ctx: APIRequestContext, ref: string) {
  const res = await ctx.get('/api/flights?limit=200');
  expect(res.ok()).toBeTruthy();
  const all = (await res.json()).flights as Array<Record<string, unknown>>;
  return all.filter((f) => f.booking_reference === ref);
}

function uniqueRef(prefix: string): string {
  return (prefix + Math.random().toString(36).slice(2).toUpperCase()).slice(0, 6);
}

/** A day in the coming year no earlier run is likely to have used. */
function randomDay(): { token: string; next: string } {
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  const m = months[Math.floor(Math.random() * 12)];
  const d = 1 + Math.floor(Math.random() * 26);
  const pad = (n: number) => String(n).padStart(2, '0');
  return { token: `${pad(d)}${m}`, next: `${pad(d + 1)}${m}` };
}

// Issue dates far enough back that every day of next year resolves forward from them.
const ISSUED = 'Mon, 04 Jan 2027 10:00:00 +0000';
const CHANGED = 'Tue, 05 Jan 2027 10:00:00 +0000';

test('a reissued receipt with new times keeps the previous ones on the row', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping reschedule tests');
  const ref = uniqueRef('RS');
  const day = randomDay();

  await uploadEml(ctx!, 'ticket.eml', buildEml({
    from: 'tickets@example.com', subject: 'Electronic ticket receipt', date: ISSUED,
    text: receipt(ref, [`TP 783 / ${day.token} ARN - LIS 19:05 22:35`]),
  }));
  const [before] = await flightsFor(ctx!, ref);
  expect(before).toBeTruthy();
  expect(before.rescheduled_at).toBeNull();

  await uploadEml(ctx!, 'reissue.eml', buildEml({
    from: 'tickets@example.com', subject: 'Electronic ticket receipt', date: CHANGED,
    text: receipt(ref, [`TP 783 / ${day.token} ARN - LIS 19:30 23:00`]),
  }));
  const rows = await flightsFor(ctx!, ref);
  // Instants come back in UTC, so compare against what the row held before
  // rather than against the printed local clocks.
  expect(rows).toHaveLength(1);
  expect(rows[0].id).toBe(before.id);
  expect(rows[0].departure_datetime).not.toBe(before.departure_datetime);
  expect(rows[0].rescheduled_from_departure).toBe(before.departure_datetime);
  expect(rows[0].rescheduled_from_arrival).toBe(before.arrival_datetime);
  expect(rows[0].rescheduled_at).not.toBeNull();

  await ctx!.delete(`/api/flights/${before.id}`);
});

test('a leg moved to the next day lands on the same row, not beside it', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping reschedule tests');
  const ref = uniqueRef('MV');
  const day = randomDay();

  await uploadEml(ctx!, 'ticket.eml', buildEml({
    from: 'tickets@example.com', subject: 'Electronic ticket receipt', date: ISSUED,
    text: receipt(ref, [`TP 783 / ${day.token} ARN - LIS 19:05 22:35`]),
  }));
  const [before] = await flightsFor(ctx!, ref);
  await uploadEml(ctx!, 'reissue.eml', buildEml({
    from: 'tickets@example.com', subject: 'Electronic ticket receipt', date: CHANGED,
    text: receipt(ref, [`TP 783 / ${day.next} ARN - LIS 07:00 10:30`]),
  }));
  const rows = await flightsFor(ctx!, ref);
  expect(rows).toHaveLength(1);
  expect(rows[0].id).toBe(before.id);
  expect(String(rows[0].departure_datetime).slice(0, 10)).not.toBe(
    String(before.departure_datetime).slice(0, 10),
  );
  expect(rows[0].rescheduled_from_departure).toBe(before.departure_datetime);

  await ctx!.delete(`/api/flights/${before.id}`);
});

test("a SAS notice without an itinerary flags the booking's legs", async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping reschedule tests');
  const ref = uniqueRef('NT');
  const day = randomDay();

  await uploadEml(ctx!, 'ticket.eml', buildEml({
    from: 'tickets@example.com', subject: 'Electronic ticket receipt', date: ISSUED,
    text: receipt(ref, [`SK 1401 / ${day.token} ARN - CPH 08:00 09:10`]),
  }));
  const [before] = await flightsFor(ctx!, ref);
  await uploadEml(ctx!, 'notice.eml', buildEml({
    from: '"SAS" <no-reply@msg.flysas.com>',
    subject: `Schedule change from SAS - Booking reference ${ref}`,
    date: CHANGED,
    text: [
      `Important information about your SAS booking ${ref}`,
      '',
      `Unfortunately, we've had to change our flight schedule which has impacted your trip with booking reference ${ref}.`,
      'Please see our suggested new itinerary in My bookings.',
      'You now have three options: travel on the new flight(s), rebook free of charge, or cancel your booking.',
      '',
    ].join('\n'),
  }));
  const rows = await flightsFor(ctx!, ref);
  expect(rows).toHaveLength(1);
  expect(rows[0].schedule_change_notice_at).not.toBeNull();
  expect(rows[0].status).not.toBe('cancelled');

  await ctx!.delete(`/api/flights/${before.id}`);
});
