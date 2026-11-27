/**
 * E2E for Booking.com's broker car-rental confirmation.
 *
 * `cars.booking.com` sends HTML whose plain-text part is only a "view online"
 * link, so the whole path has to read the HTML part, take the supplier from
 * `Rental company`, and carry the two counter times into the importer. The
 * fixture is synthetic: no real names, references, phones or addresses.
 */

import process from 'node:process';
import { expect, request, test, type APIRequestContext } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';

const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:8000';
const USER = ACCOUNTS.bookingCarUser;
const REF = 'E2ECARBOOK123';
const VEHICLE = 'Peugeot 208 or similar';

const HTML = `<html><body>
<div>Confirmation:</div><div>${REF}</div>
<div>Test Driver, your car hire for Lisbon Airport is confirmed!</div>
<div>Your checklist</div><div>${VEHICLE}</div><div>Manual gearbox</div>
<div>Pick-up</div>
<div>Saturday, 4 December 2027 10:30</div>
<div>Lisbon Airport</div>
<div>Drop-off</div>
<div>Tuesday, 7 December 2027 18:00</div>
<div>Lisbon Airport, Lisbon, Portugal, 1700-008</div>
<div>Driver details</div><div>Test Driver</div><div>tester@example.com</div>
<div>Rental company</div><div>Budget</div>
</body></html>`;

async function login(): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', {
    data: { username: USER.username, password: USER.password },
  });
  expect(res.ok(), `sign in as ${USER.username}: ${await res.text()}`).toBeTruthy();
  return ctx;
}

function bookingCarEml(): Buffer {
  return Buffer.from(
    [
      'From: Booking.com <no-reply@cars.booking.com>',
      'To: tester@example.com',
      'Subject: Thanks! Your car rental with Budget at Lisbon Airport is confirmed',
      'Date: Fri, 5 Nov 2027 10:00:00 +0000',
      `Message-ID: <e2e-booking-car-${Math.random().toString(36).slice(2)}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/html; charset="utf-8"',
      '',
      HTML,
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

type Rental = {
  trip_id: string;
  vendor: string;
  booking_reference: string | null;
  pickup: { name: string };
  pickup_date: string;
  dropoff_date: string;
  vehicle: string | null;
  driver_name: string | null;
};

async function findRental(ctx: APIRequestContext): Promise<Rental | null> {
  const trips = (await (await ctx.get('/api/trips')).json()).trips ?? [];
  for (const trip of trips) {
    const res = await ctx.get(`/api/trips/${trip.id}/car-rentals`);
    if (!res.ok()) continue;
    const match = ((await res.json()) as Rental[]).find((r) => r.booking_reference === REF);
    if (match) return match;
  }
  return null;
}

test('a Booking.com car confirmation imports the supplier and both counters', async () => {
  const ctx = await login();
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: {
      files: {
        name: 'booking-car.eml',
        mimeType: 'message/rfc822',
        buffer: bookingCarEml(),
      },
    },
  });
  expect(res.ok(), `upload booking car: ${await res.text()}`).toBeTruthy();

  // End state, not `car_rentals_created`: a re-run correctly finds the same
  // booking and declines to duplicate it.
  const rental = await findRental(ctx);
  expect(rental, 'the confirmation should have produced a rental').not.toBeNull();
  expect(rental!.vendor).toBe('Budget');
  expect(rental!.pickup.name).toBe('Lisbon Airport');
  expect(rental!.pickup_date).toBe('2027-12-04');
  expect(rental!.dropoff_date).toBe('2027-12-07');
  expect(rental!.vehicle).toBe(VEHICLE);
  expect(rental!.driver_name).toBe('Test Driver');

  const trip = (await (await ctx.get(`/api/trips/${rental!.trip_id}`)).json()) as {
    start_date: string;
    end_date: string;
  };
  expect(trip.start_date).toBe('2027-12-04');
  expect(trip.end_date).toBe('2027-12-07');

  await ctx.dispose();
});
