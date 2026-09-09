/**
 * E2E tests for .eml upload parsing (POST /api/sync/upload-eml).
 *
 * This is the one user-facing flow that runs the whole extraction pipeline
 * end-to-end, so it is where the removal of the generic line scanners is
 * verified against a live server: a Vueling booking confirmation must import
 * both legs through Vueling's own rule, and a marketing email that merely
 * mentions a flight-number-shaped token must import nothing at all.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const USER = 'e2e_eml_user';
const PASS = 'E2eEmlUser1!';

async function loginContext(username: string, password: string): Promise<APIRequestContext | null> {
  const ctx = await request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username, password } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

async function ensureUser(): Promise<APIRequestContext | null> {
  const anon = await request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: USER, password: PASS },
  });
  await anon.dispose();

  if (setupRes.ok() || setupRes.status() === 409) {
    return loginContext(USER, PASS);
  }
  return null;
}

/** Build a minimal multipart/alternative .eml with an HTML part. */
function buildEml(opts: { from: string; subject: string; date: string; html: string }): Buffer {
  const raw = [
    `From: ${opts.from}`,
    `To: traveller@example.com`,
    `Subject: ${opts.subject}`,
    `Date: ${opts.date}`,
    `Message-ID: <e2e-eml-${Math.random().toString(36).slice(2)}@example.com>`,
    'MIME-Version: 1.0',
    'Content-Type: text/html; charset="utf-8"',
    '',
    opts.html,
    '',
  ].join('\r\n');
  return Buffer.from(raw, 'utf-8');
}

const VUELING_HTML = `<html><body>
<p>Booking code</p><p>E2ETST</p>
<p>Outbound</p><p>Basic</p>
<p>Wednesday, 27 April 2022</p>
<p>Stockholm (T2)</p><p>Barcelona (T1)</p>
<p>ARN</p><p>BCN</p>
<p>11:35h</p><p>15:20h</p>
<p>VY1266</p>
<p>Return</p><p>Basic</p>
<p>Sunday, 01 May 2022</p>
<p>Barcelona (T1)</p><p>Stockholm (T2)</p>
<p>BCN</p><p>ARN</p>
<p>15:25h</p><p>19:10h</p>
<p>VY1265</p>
</body></html>`;

// A promo mail that name-drops a flight-number-shaped token next to city names
// and times. The old generic scanner was exactly the thing that would stitch
// these fragments into a flight; nothing in the pipeline should now.
const MARKETING_HTML = `<html><body>
<p>Your flights can be even better</p>
<p>Upgrade your flight thanks to Avios</p>
<p>IB0828</p>
<p>Stockholm</p><p>Madrid</p>
<p>18:35</p><p>22:40</p>
<p>17 September 2026</p>
<p>Loyalty card</p><p>for free</p>
</body></html>`;

async function uploadEml(ctx: APIRequestContext, name: string, buffer: Buffer) {
  return ctx.post('/api/sync/upload-eml', {
    multipart: {
      files: { name, mimeType: 'message/rfc822', buffer },
    },
  });
}

test('uploading a Vueling booking confirmation imports both legs', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping .eml upload tests');

  const eml = buildEml({
    from: 'Vueling Airlines <no-reply@vueling.com>',
    subject: 'Your booking confirmation - E2ETST ARN-BCN 27 April, BCN-ARN 1 May',
    date: 'Tue, 8 Feb 2022 14:12:00 +0100',
    html: VUELING_HTML,
  });

  const res = await uploadEml(ctx!, 'vueling.eml', eml);
  expect(res.ok()).toBeTruthy();

  const body = await res.json();
  expect(body.emails_processed).toBe(1);

  // Asserted on end state rather than on the create/update counters: a re-run of
  // this spec re-uploads the same itinerary, which the pipeline correctly
  // deduplicates, so both counters legitimately come back 0 the second time.
  const flightsRes = await ctx!.get('/api/flights?limit=200');
  expect(flightsRes.ok()).toBeTruthy();
  const flights = (await flightsRes.json()).flights;
  const numbers = flights.map((f: { flight_number: string }) => f.flight_number);
  expect(numbers).toContain('VY1266');
  expect(numbers).toContain('VY1265');

  const outbound = flights.find((f: { flight_number: string }) => f.flight_number === 'VY1266');
  expect(outbound.departure_airport).toBe('ARN');
  expect(outbound.arrival_airport).toBe('BCN');

  // Regression: the two city lines precede both IATA lines, so a naive pairwise
  // read of the block would give the return leg the wrong direction.
  const inbound = flights.find((f: { flight_number: string }) => f.flight_number === 'VY1265');
  expect(inbound.departure_airport).toBe('BCN');
  expect(inbound.arrival_airport).toBe('ARN');

  await ctx!.dispose();
});

test('uploading a marketing email imports no flights', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping .eml upload tests');

  const before = (await (await ctx!.get('/api/flights?limit=200')).json()).flights;

  const eml = buildEml({
    from: 'Iberia <no-reply@comunicaciones.iberia.com>',
    subject: 'Your flights can be even better',
    date: 'Mon, 1 Sep 2026 09:00:00 +0200',
    html: MARKETING_HTML,
  });

  const res = await uploadEml(ctx!, 'marketing.eml', eml);
  expect(res.ok()).toBeTruthy();

  const body = await res.json();
  expect(body.flights_created).toBe(0);

  const after = (await (await ctx!.get('/api/flights?limit=200')).json()).flights;
  expect(after.length).toBe(before.length);

  await ctx!.dispose();
});
