/**
 * Prepares the server under test before any spec runs: every account in
 * `support/accounts.ts`, and a seeded trip owned by `E2E_BROWSER` whose session
 * is saved for the specs that browse rather than set up their own data.
 *
 * Needs the server started with `DISABLE_RATE_LIMITS=true` (two dozen sign-ins
 * from one address in a minute are exactly what the 5/minute login limit stops)
 * and `SECURE_COOKIES=false` (the suite talks plain http to localhost).
 *
 * On a server that already has accounts this signs in as `E2E_ADMIN` and tops
 * up whatever is missing. If it cannot — a developer's own server, owned by
 * someone else — it says so and writes an empty session, and the specs fall
 * back to skipping exactly as they did before this file existed.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import process from 'node:process';
import { request, type APIRequestContext, type APIResponse, type FullConfig } from '@playwright/test';
import { ALL_ACCOUNTS, E2E_ADMIN, E2E_BROWSER, type E2EAccount } from './support/accounts';
import {
  AUTH_DIR,
  BROWSER_STATE,
  SEED_BOOKING_REF,
  STOPOVER_BOOKING_REF,
  seedReceipt,
  stopoverReceipt,
  writeSeedInfo,
} from './support/seed';

const EMPTY_STATE = JSON.stringify({ cookies: [], origins: [] });

function write(file: string, data: string) {
  writeFileSync(file, data, 'utf-8');
}

async function signIn(baseURL: string, account: E2EAccount): Promise<APIRequestContext | null> {
  const ctx = await request.newContext({ baseURL });
  const res = await ctx.post('/api/auth/login', {
    data: { username: account.username, password: account.password },
  });
  if (res.ok()) return ctx;
  await ctx.dispose();
  return null;
}

async function ensureAdmin(baseURL: string): Promise<APIRequestContext | null> {
  const anon = await request.newContext({ baseURL });
  // Answers 200 only on an empty server; 409 otherwise, which is fine.
  await anon.post('/api/auth/setup', {
    data: { username: E2E_ADMIN.username, password: E2E_ADMIN.password },
  });
  await anon.dispose();
  return signIn(baseURL, E2E_ADMIN);
}

async function ensureAccounts(admin: APIRequestContext): Promise<void> {
  for (const account of ALL_ACCOUNTS) {
    const res = await admin.post('/api/users', {
      data: { username: account.username, password: account.password, is_admin: !!account.admin },
    });
    // An account left over from an earlier run answers "already taken"; any
    // other refusal (a password the server rejects, say) is a real failure.
    if (!res.ok() && !(res.status() === 400 && (await res.text()).includes('already taken'))) {
      throw new Error(`Creating ${account.username} failed: ${res.status()} ${await res.text()}`);
    }
  }
}

/**
 * A pending invitation from the admin, so the browser account's inbox has an
 * invitation card (accept/reject) and the notification that announces it (which
 * can be deleted) — the notifications specs otherwise skip on an empty inbox,
 * which on a fresh server is every time. Topped up when either is missing: the
 * delete test removes the notification while the invitation stays pending.
 */
async function seedInvitation(admin: APIRequestContext, browser: APIRequestContext): Promise<void> {
  const pending = await browser.get('/api/trips/invitations');
  const inbox = await browser.get('/api/notifications/inbox');
  const hasInvitation = pending.ok() && (await pending.json()).length > 0;
  const hasNotification = inbox.ok() && (await inbox.json()).length > 0;
  if (hasInvitation && hasNotification) return;
  const trip = await admin.post('/api/trips', { data: { name: 'E2E invitation' } });
  if (!trip.ok()) throw new Error(`Creating the invitation trip failed: ${trip.status()}`);
  const { id } = await trip.json();
  const share = await admin.post(`/api/trips/${id}/share`, { data: { username: E2E_BROWSER.username } });
  if (!share.ok()) throw new Error(`Inviting ${E2E_BROWSER.username} failed: ${share.status()} ${await share.text()}`);
}

/** The trip a booking's flights were grouped into, importing the receipt first if needed. */
async function importTrip(ctx: APIRequestContext, ref: string, receipt: () => Buffer): Promise<string> {
  const findTrip = async () => {
    const res = await ctx.get('/api/flights?limit=500');
    if (!res.ok()) return null;
    const flights = (await res.json()).flights as Array<{ booking_reference: string; trip_id: string | null }>;
    return flights.find((f) => f.booking_reference === ref && f.trip_id)?.trip_id ?? null;
  };

  const existing = await findTrip();
  if (existing) return existing;
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name: `${ref}.eml`, mimeType: 'message/rfc822', buffer: receipt() } },
  });
  if (!res.ok()) throw new Error(`Importing ${ref} failed: ${res.status()} ${await res.text()}`);
  const tripId = await findTrip();
  // Almost always an empty airports table: the receipts name IATA codes.
  if (!tripId) throw new Error(`The ${ref} receipt imported no trip — is the airports table loaded?`);
  return tripId;
}

/** Throws with status and body unless the response is a success. */
async function ok<T = unknown>(what: string, res: APIResponse): Promise<T> {
  if (!res.ok()) throw new Error(`${what} failed: ${res.status()} ${await res.text()}`);
  return (await res.json()) as T;
}

async function seedBrowserTrip(ctx: APIRequestContext): Promise<string> {
  const tripId = await importTrip(ctx, SEED_BOOKING_REF, seedReceipt);

  // A fixture that silently failed to create would turn the specs relying on
  // it into skips ("no packing items"), so every call here is checked.
  const packing = await ok<unknown[]>('Reading the packing list', await ctx.get(`/api/trips/${tripId}/packing`));
  if (packing.length === 0) {
    for (const text of ['Passport', 'Charger', 'Sunglasses']) {
      await ok(`Adding packing item ${text}`, await ctx.post(`/api/trips/${tripId}/packing`, { data: { text } }));
    }
  }
  const expenses = await ok<unknown[]>('Reading expenses', await ctx.get(`/api/trips/${tripId}/expenses`));
  if (expenses.length === 0) {
    await ok(
      'Adding the seeded expense',
      await ctx.post(`/api/trips/${tripId}/expenses`, {
        data: { description: 'Airport coach into the city centre', amount: 18, currency: 'EUR' },
      }),
    );
  }
  return tripId;
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use.baseURL ?? 'http://localhost:8000';
  mkdirSync(AUTH_DIR, { recursive: true });

  const admin = await ensureAdmin(baseURL);
  if (!admin) {
    // On CI the server is always fresh, so this is a broken setup, not someone
    // else's server — failing here beats a green run of skipped tests.
    if (process.env.CI) {
      throw new Error(`[e2e] Could not sign in as ${E2E_ADMIN.username} on ${baseURL}`);
    }
    console.warn(
      `[e2e] Could not sign in as ${E2E_ADMIN.username}: this server belongs to someone else. ` +
        'Specs that need accounts or seeded data will skip.',
    );
    write(BROWSER_STATE, EMPTY_STATE);
    writeSeedInfo({ available: false, tripId: null }, write);
    return;
  }

  let browser: APIRequestContext | null = null;
  try {
    await ensureAccounts(admin);
    browser = await signIn(baseURL, E2E_BROWSER);
    if (!browser) throw new Error(`Could not sign in as ${E2E_BROWSER.username} after creating it`);
    writeSeedInfo(
      {
        available: true,
        tripId: await seedBrowserTrip(browser),
        stopoverTripId: await importTrip(browser, STOPOVER_BOOKING_REF, stopoverReceipt),
      },
      write,
    );
    await seedInvitation(admin, browser);
    await browser.storageState({ path: BROWSER_STATE });
  } finally {
    await admin.dispose();
    await browser?.dispose();
  }
}
