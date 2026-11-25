/**
 * E2E for importing KDE Itinerary's train legs and bookings from an email.
 *
 * Runs the whole path against a live server: .eml upload → the KItinerary tier
 * (a stand-in for the x86_64-only binary, tests/fixtures/fake-kitinerary-extractor,
 * which scripts/run_e2e.sh points the server at) → a train leg on a new trip and
 * a "booked" concert in that trip's planner → both on the trip page.
 *
 * The stand-in answers only for an email carrying E2E-KIT-JOURNEY; its station
 * names appear in the email body, which the importer requires.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

const USER = ACCOUNTS.kitUser.username;
const PASS = ACCOUNTS.kitUser.password;

function eml(): Buffer {
  return Buffer.from(
    [
      'From: SJ <noreply@sj.example>',
      'To: traveller@example.com',
      'Subject: Din resa E2E-KIT-JOURNEY',
      'Date: Tue, 05 Jan 2027 10:00:00 +0000',
      `Message-ID: <e2e-kit-${Math.random().toString(36).slice(2)}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset="utf-8"',
      '',
      'E2E-KIT-JOURNEY',
      'Stockholm Central 07:30 -> Oslo Central 12:30, SJ 10, coach 3 seat 12',
      'E2E Fjord Concert, Oslo Opera House, 20:00',
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

async function api(): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000' });
  const res = await ctx.post('/api/auth/login', { data: { username: USER, password: PASS } });
  expect(res.ok()).toBeTruthy();
  return ctx;
}

async function upload(ctx: APIRequestContext) {
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name: 'sj.eml', mimeType: 'message/rfc822', buffer: eml() } },
  });
  expect(res.ok()).toBeTruthy();
}

type Segment = { trip_id: string; type: string; number: string | null; seat: string | null };

async function trainTrip(ctx: APIRequestContext): Promise<{ tripId: string; segments: Segment[] }> {
  const trips = (await (await ctx.get('/api/trips')).json()).trips as { id: string; name: string }[];
  const trip = trips.find((t) => t.name.startsWith('Oslo'));
  expect(trip, 'a trip opened by the train booking').toBeTruthy();
  const segments = (await (await ctx.get(`/api/trips/${trip!.id}/segments`)).json()) as Segment[];
  return { tripId: trip!.id, segments };
}

test('a train booking becomes a trip with its leg, and a concert lands in its planner', async ({
  page,
}) => {
  const ctx = await api();
  await upload(ctx);

  const { tripId, segments } = await trainTrip(ctx);
  expect(segments).toHaveLength(1);
  expect(segments[0]).toMatchObject({ type: 'train', number: 'SJ 10', seat: 'Coach 3, seat 12' });

  const plan = await (await ctx.get(`/api/trips/${tripId}/plan`)).json();
  const concert = (plan.items as { title: string; status: string; date: string; time: string }[]).find(
    (i) => i.title === 'E2E Fjord Concert',
  );
  expect(concert).toMatchObject({ status: 'booked', date: '2027-03-13', time: '20:00' });

  // Reading the same email again adds nothing.
  await upload(ctx);
  const again = await trainTrip(ctx);
  expect(again.segments).toHaveLength(1);
  const planAgain = await (await ctx.get(`/api/trips/${tripId}/plan`)).json();
  expect(planAgain.items.filter((i: { title: string }) => i.title === 'E2E Fjord Concert')).toHaveLength(1);
  await ctx.dispose();

  // And both show on the trip page: the leg in Transport, the concert on its day.
  await signInPage(page, USER, PASS);
  await page.goto(`/#/trips/${tripId}`);
  await expect(page.getByText('Oslo Central').first()).toBeVisible({ timeout: 15000 });
  // The day card lists planner items as editable titles, so read the fields'
  // values rather than the page text.
  const titles = page.getByRole('textbox', { name: 'Title' });
  await expect
    .poll(() => titles.evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value)))
    .toContain('E2E Fjord Concert');
});
