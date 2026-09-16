/**
 * E2E tests for the trash and the activity log.
 *
 * A deleted trip used to be gone for good, and — because its mails stayed in
 * the processed-mail ledger — could not even be re-imported. These drive the
 * real server: import a booking, delete its trip, see it in the trash, import
 * the same mail again (the reason people delete in this app), restore, and
 * read the story back from the activity log.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';

const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:8000';
const USER = 'e2e_trash_user';
const PASS = 'E2eTrashUser1!';

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

async function ensureUser(): Promise<APIRequestContext | null> {
  if (resolved) return cachedCtx;
  resolved = true;
  const anon = await request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', { data: { username: USER, password: PASS } });
  await anon.dispose();
  if (setupRes.ok() || setupRes.status() === 409) cachedCtx = await loginContext();
  return cachedCtx;
}

function buildEml(ref: string, legs: string[]): Buffer {
  const text = ['ELECTRONIC TICKET RECEIPT', `BOOKING REF: ${ref}`, ...legs, ''].join('\n');
  return Buffer.from(
    [
      'From: tickets@example.com',
      'To: traveller@example.com',
      'Subject: Electronic ticket receipt',
      'Date: Mon, 04 Jan 2027 10:00:00 +0000',
      `Message-ID: <e2e-trash-${ref}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset="utf-8"',
      '',
      text,
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

async function upload(ctx: APIRequestContext, ref: string, legs: string[]) {
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name: `${ref}.eml`, mimeType: 'message/rfc822', buffer: buildEml(ref, legs) } },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as { flights_created: number };
}

async function flightsFor(ctx: APIRequestContext, ref: string) {
  const res = await ctx.get('/api/flights?limit=500');
  expect(res.ok()).toBeTruthy();
  const all = (await res.json()).flights as Array<Record<string, unknown>>;
  return all.filter((f) => f.booking_reference === ref);
}

function uniqueRef(prefix: string): string {
  return (prefix + Math.random().toString(36).slice(2).toUpperCase()).slice(0, 6);
}

function randomDay(): string {
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  return `${String(1 + Math.floor(Math.random() * 27)).padStart(2, '0')}${months[Math.floor(Math.random() * 12)]}`;
}

test('a deleted trip goes to the trash, can be re-imported, and can be restored', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping trash tests');
  const ref = uniqueRef('TR');
  const leg = `TP 783 / ${randomDay()} ARN - LIS 19:05 22:35`;

  await upload(ctx!, ref, [leg]);
  const [flight] = await flightsFor(ctx!, ref);
  expect(flight).toBeTruthy();
  const tripId = flight.trip_id as string;
  expect(tripId).toBeTruthy();
  await ctx!.put(`/api/trips/${tripId}/note`, { data: { note: 'remember this' } });

  // Delete: gone from the app, present in the trash with its contents.
  expect((await ctx!.delete(`/api/trips/${tripId}`)).status()).toBe(204);
  expect((await ctx!.get(`/api/trips/${tripId}`)).status()).toBe(404);
  expect(await flightsFor(ctx!, ref)).toHaveLength(0);
  const trash = (await (await ctx!.get('/api/trash')).json()) as Array<Record<string, unknown>>;
  const item = trash.find((i) => i.entity_id === tripId)!;
  expect(item).toBeTruthy();
  expect((item.summary as { flight_count: number; has_notes: boolean }).flight_count).toBe(1);
  expect((item.summary as { has_notes: boolean }).has_notes).toBe(true);

  // The point of deleting: the same mail imports again as fresh rows.
  const again = await upload(ctx!, ref, [leg]);
  expect(again.flights_created).toBe(1);
  expect(await flightsFor(ctx!, ref)).toHaveLength(1);

  // Restore over the re-import: the trip and its note come back, the flight
  // that already exists is reported as skipped, nothing is duplicated.
  const restore = await ctx!.post(`/api/trash/${item.id}/restore`);
  expect(restore.ok()).toBeTruthy();
  const result = (await restore.json()) as { restored: Record<string, number>; skipped: Record<string, number> };
  expect(result.restored.trips).toBe(1);
  expect(result.skipped.flights).toBe(1);
  expect((await (await ctx!.get(`/api/trips/${tripId}`)).json()).note).toBe('remember this');
  expect(await flightsFor(ctx!, ref)).toHaveLength(1);

  // The activity log tells the story, newest first.
  const activity = (await (await ctx!.get('/api/activity')).json()) as Array<{ action: string; entity_id: string | null }>;
  const mine = activity.filter((a) => a.entity_id === tripId).map((a) => a.action);
  expect(mine).toEqual(['trip.restored', 'trip.trashed']);

  // Cleanup: both trips now hold legs for this ref; trash what remains.
  const rows = await flightsFor(ctx!, ref);
  for (const r of rows) await ctx!.delete(`/api/flights/${r.id}`);
});

test('a deleted flight is in the trash and comes back to its trip', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping trash tests');
  const ref = uniqueRef('TF');
  await upload(ctx!, ref, [`TP 783 / ${randomDay()} ARN - LIS 19:05 22:35`]);
  const [flight] = await flightsFor(ctx!, ref);

  expect((await ctx!.delete(`/api/flights/${flight.id}`)).ok()).toBeTruthy();
  expect(await flightsFor(ctx!, ref)).toHaveLength(0);
  const trash = (await (await ctx!.get('/api/trash')).json()) as Array<Record<string, unknown>>;
  const item = trash.find((i) => i.entity_id === flight.id)!;
  expect(item.kind).toBe('flight');

  expect((await ctx!.post(`/api/trash/${item.id}/restore`)).ok()).toBeTruthy();
  const [back] = await flightsFor(ctx!, ref);
  expect(back.id).toBe(flight.id);
  expect(back.trip_id).toBe(flight.trip_id);

  await ctx!.delete(`/api/trips/${flight.trip_id}`);
});

test('permanent delete removes the trash entry and is logged', async () => {
  const ctx = await ensureUser();
  test.skip(!ctx, 'Could not set up user — skipping trash tests');
  const ref = uniqueRef('TP');
  await upload(ctx!, ref, [`TP 783 / ${randomDay()} ARN - LIS 19:05 22:35`]);
  const [flight] = await flightsFor(ctx!, ref);
  await ctx!.delete(`/api/trips/${flight.trip_id}`);
  const trash = (await (await ctx!.get('/api/trash')).json()) as Array<Record<string, unknown>>;
  const item = trash.find((i) => i.entity_id === flight.trip_id)!;

  expect((await ctx!.delete(`/api/trash/${item.id}`)).status()).toBe(204);
  expect((await ctx!.post(`/api/trash/${item.id}/restore`)).status()).toBe(404);
  const activity = (await (await ctx!.get('/api/activity')).json()) as Array<{ action: string; entity_id: string | null }>;
  expect(activity.find((a) => a.action === 'trip.purged' && a.entity_id === flight.trip_id)).toBeTruthy();
});
