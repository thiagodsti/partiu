/**
 * E2E for autoforwarded booking mail.
 *
 * A forward replaces the envelope From with the traveller's mailbox, so the
 * Booking.com and rental template readers have to read the original headers
 * quoted in the body — the same thing the airline rules have always done.
 * Uploading the forwarded copy drives the real pipeline end to end; the IMAP
 * fetch filter is covered by the backend suite.
 */

import process from 'node:process';
import { expect, request, test, type APIRequestContext } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';

const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:8000';
const USER = ACCOUNTS.forwardUser;
const STAY_REF = String(Date.now()).slice(-9);
const RENTAL_REF = `X${Date.now()}`;

async function login(): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', {
    data: { username: USER.username, password: USER.password },
  });
  expect(res.ok(), `sign in as ${USER.username}: ${await res.text()}`).toBeTruthy();
  return ctx;
}

/** A forward with the original headers in the text part and no HTML fallback. */
function forwardedEml(originalFrom: string, originalSubject: string, bookingText: string): Buffer {
  return Buffer.from(
    [
      'From: "Traveller" <traveller@example.com>',
      'To: travel@samsel.org',
      'Subject: Fwd',
      'Date: Fri, 27 Nov 2026 10:00:00 +0000',
      `Message-ID: <e2e-forward-${Math.random().toString(36).slice(2)}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset="utf-8"',
      '',
      '---------- Forwarded message ---------',
      `From: ${originalFrom}`,
      `Subject: ${originalSubject}`,
      'Date: Fri, 27 Nov 2026 09:59:00 +0000',
      'To: traveller@example.com',
      '',
      bookingText,
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

async function upload(ctx: APIRequestContext, name: string, eml: Buffer) {
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name, mimeType: 'message/rfc822', buffer: eml } },
  });
  expect(res.ok(), `upload ${name}: ${await res.text()}`).toBeTruthy();
  return res.json();
}

type Stay = { booking_reference: string | null; place: { name: string } };

async function findStay(ctx: APIRequestContext, ref: string): Promise<Stay | null> {
  const trips = (await (await ctx.get('/api/trips')).json()).trips ?? [];
  for (const trip of trips) {
    const res = await ctx.get(`/api/trips/${trip.id}/stays`);
    if (!res.ok()) continue;
    const match = ((await res.json()) as Stay[]).find((s) => s.booking_reference === ref);
    if (match) return match;
  }
  return null;
}

test('a forwarded Booking.com confirmation imports the stay', async () => {
  const ctx = await login();
  const property = 'E2E Forwarded Harbour Hotel';
  const bookingText = [
    'Booking.com',
    `Confirmation: ${STAY_REF}`,
    'Thanks Test! Your booking in Porto is confirmed.',
    property,
    'is expecting you on Fri 3 Nov',
    'Your reservation is paid with Booking.com',
    'Reservation details',
    'Check-in Friday, 3 November 2028 (15:00 - 23:00)',
    'Check-out Sunday, 5 November 2028 (until 11:00)',
    'Your reservation 2 nights, Twin Room',
    'You booked for 2 adults',
    'Location',
    '1 Example Street, 4000-000 Porto, Portugal',
    'Phone +351000000000',
  ].join('\n');

  const result = await upload(
    ctx,
    'forwarded-booking.eml',
    forwardedEml(
      'noreply@booking.com',
      `Thanks! Your booking is confirmed at ${property}`,
      bookingText,
    ),
  );
  expect(result.stays_created).toBe(1);

  const stay = await findStay(ctx, STAY_REF);
  expect(stay).not.toBeNull();
  expect(stay!.place.name).toBe(property);
  await ctx.dispose();
});

test('a forwarded Hertz confirmation imports the rental', async () => {
  const ctx = await login();
  const bookingText = [
    'My Hertz Reservation',
    'Confirmation',
    RENTAL_REF,
    'Sample Traveller',
    'Mini, 2-3 Door, Manual, Air',
    '(A) Fiat 500',
    'or similar',
    'Your Trip Itinerary',
    'Pickup Location',
    'Vienna Airport',
    'Schwechat Airport',
    'Vienna,',
    'AT 1300',
    'Pickup Date & Time',
    'Fri, Nov 3, 2028 at 09:30 AM',
    'Drop-off Location',
    'Vienna Airport',
    'Schwechat Airport',
    'Vienna,',
    'AT 1300',
    'Drop-off Date & Time',
    'Sun, Nov 5, 2028 at 11:00 AM',
  ].join('\n');

  const result = await upload(
    ctx,
    'forwarded-hertz.eml',
    forwardedEml('reservations@emails.hertz.com', 'My Hertz Reservation', bookingText),
  );
  expect(result.car_rentals_created).toBe(1);
  await ctx.dispose();
});
