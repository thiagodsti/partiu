/**
 * The seeded trip that the browse-only specs open (`trip-detail`,
 * `add-transport`, `packing-touch`, `trip-sharing`): a round trip with a
 * connection on the way out, a packing list and an expense. Those specs used to
 * open "the first trip card" and skip when there was none, which on a fresh
 * server is always — so they had never run anywhere but a developer's own data.
 *
 * Paths here are shared between `global-setup.ts`, which writes them, and the
 * specs, which read them.
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));

export const AUTH_DIR = path.join(here, '..', '.auth');
/** Session cookie of `E2E_BROWSER`, for `test.use({ storageState })`. */
export const BROWSER_STATE = path.join(AUTH_DIR, 'browser.json');
const SEED_FILE = path.join(AUTH_DIR, 'seed.json');

export const SEED_BOOKING_REF = 'E2ESED';
export const STOPOVER_BOOKING_REF = 'E2ESTO';

export interface SeedInfo {
  /** False only when global setup could not sign in as E2E_ADMIN — someone
   * else's server, outside CI. Every other failure throws in setup instead. */
  available: boolean;
  tripId: string | null;
  /** A one-way trip that waits 25h in Copenhagen between its two legs. */
  stopoverTripId?: string | null;
}

export function writeSeedInfo(info: SeedInfo, write: (file: string, data: string) => void): void {
  write(SEED_FILE, JSON.stringify(info));
}

function readSeedInfo(): SeedInfo {
  let raw: string;
  try {
    raw = readFileSync(SEED_FILE, 'utf-8');
  } catch {
    throw new Error(`${SEED_FILE} is missing — did global setup run?`);
  }
  const info = JSON.parse(raw) as Partial<SeedInfo>;
  if (typeof info.available !== 'boolean') {
    throw new Error(`${SEED_FILE} has no "available" flag — written by an older global setup?`);
  }
  return info as SeedInfo;
}

/**
 * Skips the calling test only when global setup said this server could not be
 * prepared. Anything else that goes wrong — a sign-in that fails, a fixture
 * that will not create — must fail the test: a skip there is coverage lost
 * without anyone being told.
 */
export function requireSeededServer(): void {
  test.skip(readSeedInfo().available === false, 'Global setup could not prepare this server');
}

function requireTrip(id: string | null | undefined, which: string): string {
  requireSeededServer();
  if (typeof id !== 'string' || id === '') {
    throw new Error(`Global setup reported success but recorded no usable ${which} id (${JSON.stringify(id)})`);
  }
  return id;
}

/** The seeded round trip's id. Skips only on an unprepared server; a missing id fails. */
export function requireSeededTrip(): string {
  return requireTrip(readSeedInfo().tripId, 'seeded trip');
}

/** The seeded 25h-stopover trip's id, on the same terms as requireSeededTrip. */
export function requireStopoverTrip(): string {
  return requireTrip(readSeedInfo().stopoverTripId, 'stopover trip');
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

function ddmon(d: Date): string {
  return `${String(d.getUTCDate()).padStart(2, '0')}${MONTHS[d.getUTCMonth()]}`;
}

/**
 * A GDS ticket receipt for the seeded itinerary, issued today and travelling in
 * two months, so the trip is upcoming and on the trips list whenever this runs.
 * ARN→FRA→LIS out (a 1h30 connection) and LIS→ARN back a week later.
 */
export function seedReceipt(now = new Date()): Buffer {
  const out = new Date(now.getTime() + 60 * 86400000);
  const back = new Date(out.getTime() + 7 * 86400000);
  return receipt(now, SEED_BOOKING_REF, [
    `LH 803 / ${ddmon(out)} ARN - FRA 07:00 09:30`,
    `LH 1166 / ${ddmon(out)} FRA - LIS 11:00 13:15`,
    `TP 782 / ${ddmon(back)} LIS - ARN 06:00 10:10`,
  ]);
}

/**
 * ARN→CPH, then CPH→LIS two days later: a stopover long enough that the leg
 * divider must stop quoting a "total" for the journey. Two days rather than
 * the original 25h, because a 25h local wait across Europe's DST change is
 * exactly 24h UTC and keeps its total for half the year. Four months out, so
 * its 48h proximity window never touches the round trip above.
 */
export function stopoverReceipt(now = new Date()): Buffer {
  const first = new Date(now.getTime() + 120 * 86400000);
  const second = new Date(first.getTime() + 2 * 86400000);
  return receipt(now, STOPOVER_BOOKING_REF, [
    `SK 1417 / ${ddmon(first)} ARN - CPH 08:00 09:10`,
    `TP 753 / ${ddmon(second)} CPH - LIS 10:10 13:00`,
  ]);
}

function receipt(now: Date, ref: string, legs: string[]): Buffer {
  const text = ['ELECTRONIC TICKET RECEIPT', `BOOKING REF: ${ref}`, ...legs, ''].join('\n');
  return Buffer.from(
    [
      'From: tickets@example.com',
      'To: traveller@example.com',
      'Subject: Electronic ticket receipt',
      `Date: ${now.toUTCString().replace('GMT', '+0000')}`,
      // Unique per run: the mail's id is the flights' dedup key, and a rerun on
      // a server whose seeded trip was deleted (trip-sharing deletes its own
      // trip, but a developer may delete this one) must be able to import it again.
      `Message-ID: <e2e-seed-${ref}-${now.getTime()}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset="utf-8"',
      '',
      text,
      '',
    ].join('\r\n'),
    'utf-8',
  );
}
