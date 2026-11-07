/**
 * E2E for importing accommodation out of schema.org booking markup.
 *
 * Runs the whole path against a live server: .eml upload → the markup reader →
 * trip matching → a stay on a trip. Two things here are worth having end-to-end
 * rather than only in the backend suite. The sender is **Airbnb, which is on the
 * blocked-domain list** — the lodging reader is deliberately ahead of that skip,
 * and nothing but a live run proves the ordering survived. And a booking with no
 * flights anywhere near it has to **open a trip of its own**, which is the case
 * the feature exists for (the drive-to-the-coast trip that has no tickets).
 *
 * The markup is synthetic, for the reason CLAUDE.md gives about fixtures: real
 * confirmations carry a property's street address, a host's phone number and a
 * booking reference.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const USER = 'e2e_lodging_user';
const PASS = 'E2eLodgingUser1!';

// Stable across runs so a re-run re-imports the same booking and exercises the
// importer's idempotency rather than piling up duplicates.
const REF = 'E2ELODGING01';
const PROPERTY = 'E2E Riverside Studio';

async function loginContext(): Promise<APIRequestContext | null> {
  const ctx = await request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username: USER, password: PASS } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

async function ensureUser(): Promise<APIRequestContext | null> {
  const anon = await request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', { data: { username: USER, password: PASS } });
  await anon.dispose();
  if (setupRes.ok() || setupRes.status() === 409) return loginContext();
  return null;
}

function buildEml(opts: { from: string; subject: string; date: string; html: string }): Buffer {
  const raw = [
    `From: ${opts.from}`,
    'To: traveller@example.com',
    `Subject: ${opts.subject}`,
    `Date: ${opts.date}`,
    `Message-ID: <e2e-lodging-${Math.random().toString(36).slice(2)}@example.com>`,
    'MIME-Version: 1.0',
    'Content-Type: text/html; charset="utf-8"',
    '',
    opts.html,
    '',
  ].join('\r\n');
  return Buffer.from(raw, 'utf-8');
}

const LODGING_HTML = `<html><body>
<p>Your reservation is confirmed.</p>
<script type="application/ld+json">
{
 "@type": "LodgingReservation",
 "@context": "http://schema.org",
 "reservationNumber": "${REF}",
 "reservationStatus": "http://schema.org/ReservationConfirmed",
 "reservationFor": {
  "@type": "LodgingBusiness",
  "name": "${PROPERTY}",
  "address": {
   "@type": "PostalAddress",
   "streetAddress": "1 Example Street",
   "addressLocality": "Moneglia",
   "addressCountry": "IT"
  },
  "telephone": "+39 000 000 0000"
 },
 "checkinDate": "2027-06-07T16:00:00+01:00",
 "checkoutDate": "2027-06-10T10:00"
}
</script>
</body></html>`;

async function uploadEml(ctx: APIRequestContext, name: string, buffer: Buffer) {
  return ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name, mimeType: 'message/rfc822', buffer } },
  });
}

type Stay = { booking_reference: string | null; check_in_date: string; check_out_date: string;
              place: { name: string; country_code: string | null } };

/** GET /api/trips/{id}/stays returns a bare array, not an envelope. */
async function staysFor(ctx: APIRequestContext, tripId: string): Promise<Stay[]> {
  const res = await ctx.get(`/api/trips/${tripId}/stays`);
  return res.ok() ? await res.json() : [];
}

async function findStay(ctx: APIRequestContext) {
  const trips = (await (await ctx.get('/api/trips')).json()).trips ?? [];
  for (const trip of trips) {
    const match = (await staysFor(ctx, trip.id)).find((s) => s.booking_reference === REF);
    if (match) return { trip, stay: match };
  }
  return null;
}

test('an Airbnb booking imports a stay despite the sender being blocked', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping lodging import tests');

  const eml = buildEml({
    from: 'Airbnb <automated@airbnb.com>',
    subject: 'Reservation confirmed for Moneglia',
    date: 'Wed, 9 Jun 2027 10:00:00 +0200',
    html: LODGING_HTML,
  });

  const res = await uploadEml(ctx!, 'airbnb.eml', eml);
  expect(res.ok()).toBeTruthy();

  // Asserted on end state, not on stays_created: a re-run re-uploads the same
  // booking, which the importer correctly declines to duplicate.
  const found = await findStay(ctx!);
  expect(found, 'the booking should have produced a stay').not.toBeNull();
  expect(found!.stay.place.name).toBe(PROPERTY);
  expect(found!.stay.place.country_code).toBe('IT');

  // The check-in carried a +01:00 offset the property is not on. The wall clock
  // is what must survive — honouring the sender's offset would move it.
  expect(found!.stay.check_in_date).toBe('2027-06-07');
  expect(found!.stay.check_out_date).toBe('2027-06-10');

  // No flights anywhere near it, so it opened a trip of its own, spanning itself.
  expect(found!.trip.start_date).toBe('2027-06-07');
  expect(found!.trip.end_date).toBe('2027-06-10');

  await ctx!.dispose();
});

test('re-uploading the same booking does not duplicate the stay', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping lodging import tests');

  const eml = buildEml({
    from: 'Airbnb <automated@airbnb.com>',
    subject: 'Reservation confirmed for Moneglia',
    date: 'Wed, 9 Jun 2027 10:00:00 +0200',
    html: LODGING_HTML,
  });
  await uploadEml(ctx!, 'airbnb-again.eml', eml);

  const trips = (await (await ctx!.get('/api/trips')).json()).trips ?? [];
  let matches = 0;
  for (const trip of trips) {
    matches += (await staysFor(ctx!, trip.id)).filter((s) => s.booking_reference === REF).length;
  }
  expect(matches).toBe(1);

  await ctx!.dispose();
});

test('an email with no reservation markup imports no stay', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping lodging import tests');

  const eml = buildEml({
    from: 'Airbnb <automated@airbnb.com>',
    subject: 'Reservation reminder - 7 June 2027',
    date: 'Thu, 3 Jun 2027 10:00:00 +0200',
    html: '<html><body><p>Your stay at E2E Riverside Studio starts soon.</p></body></html>',
  });

  const res = await uploadEml(ctx!, 'reminder.eml', eml);
  expect(res.ok()).toBeTruthy();
  expect((await res.json()).stays_created).toBe(0);

  await ctx!.dispose();
});

// Booking.com ships no schema.org markup, so its confirmations are read by a
// template reader (`parsers/booking_com.py`) instead. Also a blocked sender, and
// also synthetic — the structure mirrors the real confirmation's HTML, where
// each label and its value sit in separate elements.
const BOOKING_REF = '9900112233';
const BOOKING_PROPERTY = 'E2E Harbour Hotel';
const BOOKING_HTML = `<html><body>
<p>Confirmation:</p><p>${BOOKING_REF}</p><p>PIN:</p><p>0000</p>
<p>Thanks Test! Your booking in Porto is confirmed.</p>
<p>${BOOKING_PROPERTY}</p><p>is expecting you on</p><p>Fri 3 Sep</p>
<p>Your reservation is paid with Booking.com</p>
<h2>Reservation details</h2>
<p>Check-in</p><p>Friday, 3 September 2027</p><p>(15:00 - 23:00)</p>
<p>Check-out</p><p>Sunday, 5 September 2027</p><p>(until 11:00)</p>
<p>Your reservation</p><p>2 nights</p><p>Twin Room</p>
<p>You booked for</p><p>2 adults</p>
<p>Location</p><p>1 Example Street, 4000-000 Porto, Portugal</p>
<p>Phone</p><p>+351000000000</p>
</body></html>`;

test('a Booking.com confirmation imports a stay with no markup to read', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping lodging import tests');

  const eml = buildEml({
    from: 'noreply@booking.com',
    subject: `Thanks! Your booking is confirmed at ${BOOKING_PROPERTY}`,
    date: 'Mon, 2 Aug 2027 10:00:00 +0200',
    html: BOOKING_HTML,
  });
  const res = await uploadEml(ctx!, 'booking-com.eml', eml);
  expect(res.ok()).toBeTruthy();

  const trips = (await (await ctx!.get('/api/trips')).json()).trips ?? [];
  const matches: Stay[] = [];
  for (const trip of trips) {
    matches.push(
      ...(await staysFor(ctx!, trip.id)).filter((s) => s.booking_reference === BOOKING_REF),
    );
  }
  // Exactly one, also on a re-run: the importer is idempotent on the reference.
  expect(matches).toHaveLength(1);
  expect(matches[0].place.name).toBe(BOOKING_PROPERTY);
  expect(matches[0].check_in_date).toBe('2027-09-03');
  expect(matches[0].check_out_date).toBe('2027-09-05');

  await ctx!.dispose();
});
