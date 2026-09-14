/**
 * Shared utility functions used across pages.
 * Ported from the vanilla JS page files.
 */

import type { Flight, TripSegment, TripStay } from '../api/types';

/** Read the app locale persisted in localStorage (set by i18n module). */
function appLocale(): string | undefined {
  try {
    return localStorage.getItem('locale') ?? undefined;
  } catch {
    return undefined;
  }
}

// ---- String helpers ----

export function escapeHtml(str: unknown): string {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---- Date / Time formatters ----

export function formatTime(iso: string | null | undefined, timezone?: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const opts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hour12: false };
    if (timezone) opts.timeZone = timezone;
    return d.toLocaleTimeString('en-GB', opts);
  } catch {
    return iso.slice(11, 16);
  }
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(appLocale(), { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso.slice(0, 10);
  }
}

/**
 * Day and month, no year — for the clock column of a transport row.
 *
 * The full `formatDate` runs to "26 de set. de 2026" in pt-BR, which is nearly
 * twice the width of "Sep 26, 2026" and overflowed the fixed-width column it
 * sits in, painting the date across the leg beside it. The year is the part
 * worth dropping: a row always sits inside a trip whose full dates are in the
 * header, and a leg that crosses a day gets a DateDivider spelling it out.
 */
export function formatDayMonth(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  // Stricter than formatDate, which hands an unparseable value to
  // toLocaleDateString and gets the literal string "Invalid Date" back —
  // `new Date('nonsense')` does not throw, so its try/catch never fires.
  // A row is better off showing nothing than showing those two words.
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' });
}

export function formatDateLong(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(appLocale(), {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return iso.slice(0, 10);
  }
}

export function formatDateRange(startDate: string | null | undefined, endDate: string | null | undefined): string {
  if (!startDate) return '';
  const start = formatDate(startDate);
  if (!endDate || endDate === startDate) return start;
  const end = formatDate(endDate);
  return `${start} – ${end}`;
}

export function formatDuration(minutes: number | null | undefined): string | null {
  if (!minutes) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Render a stored UTC instant as the value of a `datetime-local` input,
 * expressed in `timezone` (the IANA zone of the place it happens at).
 *
 * `<input type="datetime-local">` has no timezone of its own — it round-trips a
 * wall-clock string — so an edit form must be seeded with local time at the
 * station, not the browser's local time and not UTC. Without this, opening a
 * Beijing train for editing in a European browser would show 02:00 for an 08:00
 * departure, and saving would silently move it.
 *
 * Falls back to the browser's zone when `timezone` is unknown, which matches
 * how the backend stores times for places it could not geocode.
 */
export function toLocalInputValue(iso: string | null | undefined, timezone?: string | null): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    // en-CA gives ISO-ordered date parts, so the pieces concatenate directly.
    const date = d.toLocaleDateString('en-CA', timezone ? { timeZone: timezone } : {});
    const time = d.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      ...(timezone ? { timeZone: timezone } : {}),
    });
    return `${date}T${time}`;
  } catch {
    return iso.slice(0, 16);
  }
}

export function formatTimezone(iso: string | null | undefined, timezone: string | null | undefined): string | null {
  if (!iso || !timezone) return null;
  try {
    const d = new Date(iso);
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: timezone,
      timeZoneName: 'short',
    }).formatToParts(d);
    return parts.find((p) => p.type === 'timeZoneName')?.value ?? null;
  } catch {
    return null;
  }
}

export function formatDateTimeLocale(iso: string | null | undefined): string {
  if (!iso) return 'Never';
  try {
    const d = new Date(iso);
    return d.toLocaleString(appLocale(), {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// ---- Domain helpers ----

export function cabinLabel(cls: string | null | undefined): string {
  const map: Record<string, string> = {
    economy: 'Economy',
    premium_economy: 'Premium Economy',
    business: 'Business',
    first: 'First Class',
  };
  return map[cls ?? ''] ?? cls ?? '—';
}

export function flightStatus(f: Flight): 'completed' | 'active' | 'upcoming' {
  const now = Date.now();
  if (f.arrival_datetime && new Date(f.arrival_datetime).getTime() < now) return 'completed';
  if (f.departure_datetime && new Date(f.departure_datetime).getTime() < now) return 'active';
  return 'upcoming';
}

type Translator = (key: string, opts?: { values?: Record<string, string | number | boolean | Date | null | undefined> }) => string;

export function timeUntilTrip(startDate: string, now: number = Date.now(), t?: Translator): string {
  const diff = new Date(startDate).getTime() - now;
  if (diff <= 0) return '';

  const totalMinutes = Math.floor(diff / 60_000);
  const totalHours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);
  const hours = totalHours % 24;
  const minutes = totalMinutes % 60;

  if (!t) {
    // Fallback to hardcoded English (used in tests / non-i18n contexts)
    if (days >= 60) return `in ${Math.floor(days / 30)} months`;
    if (days >= 30) {
      const mo = Math.floor(days / 30); const rd = days % 30;
      return rd > 0 ? `in ${mo}mo ${rd}d` : `in ${mo}mo`;
    }
    if (days >= 1) return hours > 0 ? `in ${days}d ${hours}h` : `in ${days}d`;
    if (totalHours >= 1) return minutes > 0 ? `in ${hours}h ${minutes}m` : `in ${hours}h`;
    if (totalMinutes > 0) return `in ${totalMinutes}m`;
    return 'now';
  }

  if (days >= 60) return t('time.in_months', { values: { n: Math.floor(days / 30) } });
  if (days >= 30) {
    const mo = Math.floor(days / 30); const rd = days % 30;
    return rd > 0 ? t('time.in_mo_d', { values: { mo, d: rd } }) : t('time.in_mo', { values: { mo } });
  }
  if (days >= 1) return hours > 0 ? t('time.in_d_h', { values: { d: days, h: hours } }) : t('time.in_d', { values: { d: days } });
  if (totalHours >= 1) return minutes > 0 ? t('time.in_h_m', { values: { h: hours, m: minutes } }) : t('time.in_h', { values: { h: hours } });
  if (totalMinutes > 0) return t('time.in_m', { values: { m: totalMinutes } });
  return t('time.now');
}

export function inferTripStatus(trip: { start_date?: string | null; end_date?: string | null }): 'completed' | 'ongoing' | 'upcoming' {
  const now = new Date();
  if (trip.end_date) {
    // Parse as local date (not UTC) so end-of-day is midnight in the user's timezone
    const [y, m, d] = trip.end_date.split('-').map(Number);
    const endOfDay = new Date(y, m - 1, d + 1); // midnight at start of next day, local time
    if (endOfDay < now) return 'completed';
  }
  if (trip.start_date) {
    const [y, m, d] = trip.start_date.split('-').map(Number);
    if (new Date(y, m - 1, d) <= now) return 'ongoing';
  }
  return 'upcoming';
}

export function seatMapUrl(aircraft_type: string | null | undefined): string | null {
  if (!aircraft_type) return null;
  const slug = aircraft_type
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  return `https://flightseatmap.com/aircraft/${slug}-seat-map`;
}

// ---- Transport legs (flights + ground segments) ----

/**
 * The shape the shared leg logic works on. Flights and ground segments both
 * normalise into it so that layovers, day boundaries and leg totals are
 * computed once rather than twice — a train between two flights is a real
 * connection and should be treated as one.
 *
 * `departure_place` / `arrival_place` are the *display* labels: an IATA code
 * for a flight, a station name for a segment. Nothing downstream may assume
 * they are three letters.
 */
export interface TransportLeg {
  id: string;
  kind: 'flight' | 'segment';
  departure_place: string;
  arrival_place: string;
  departure_datetime: string | null;
  arrival_datetime: string | null;
  departure_timezone: string | null;
  arrival_timezone: string | null;
  duration_minutes: number | null;
  /** Present when kind === 'flight'; the row component needs the whole record. */
  flight?: Flight;
  /** Present when kind === 'segment'. */
  segment?: TripSegment;
}

export function flightToLeg(f: Flight): TransportLeg {
  return {
    id: `flight-${f.id}`,
    kind: 'flight',
    departure_place: f.departure_airport ?? '',
    arrival_place: f.arrival_airport ?? '',
    departure_datetime: f.departure_datetime,
    arrival_datetime: f.arrival_datetime,
    departure_timezone: f.departure_timezone ?? null,
    arrival_timezone: f.arrival_timezone ?? null,
    duration_minutes: f.duration_minutes ?? null,
    flight: f,
  };
}

export function segmentToLeg(s: TripSegment): TransportLeg {
  return {
    id: `segment-${s.id}`,
    kind: 'segment',
    departure_place: s.departure.name,
    arrival_place: s.arrival.name,
    departure_datetime: s.departure_datetime,
    arrival_datetime: s.arrival_datetime,
    departure_timezone: s.departure.timezone,
    arrival_timezone: s.arrival.timezone,
    duration_minutes: s.duration_minutes,
    segment: s,
  };
}

/** Epoch ms of a leg's departure; missing/unparseable sorts last rather than
 * to 1970, where it would jump to the head of the list. */
function departureInstant(leg: TransportLeg): number {
  if (!leg.departure_datetime) return Number.MAX_SAFE_INTEGER;
  const t = new Date(leg.departure_datetime).getTime();
  return isNaN(t) ? Number.MAX_SAFE_INTEGER : t;
}

function byDeparture(a: TransportLeg, b: TransportLeg): number {
  return departureInstant(a) - departureInstant(b);
}

export interface TransportBuckets {
  outbound: TransportLeg[];
  /** Legs between arriving and heading home — where ground transport lives. */
  during: TransportLeg[];
  returning: TransportLeg[] | null;
  /** False when the trip has only ground legs, so the UI can drop the
   * Outbound/Return framing entirely instead of labelling a lone train
   * "Outbound". */
  hasFlights: boolean;
}

/**
 * Group a trip's flights and ground segments into Outbound / Getting around /
 * Return.
 *
 * Outbound and Return come from `splitLegs`, which stays flight-only: coming
 * home is judged by comparing airport codes, and a station has none. Segments
 * are then placed by *when* they happen — departing after the outbound arrives
 * and before the return leaves puts a leg in the middle bucket. That middle is
 * the point of the split: a two-week trip's trains are neither the journey out
 * nor the journey home.
 */
export function splitTransport(
  flightList: Flight[],
  segmentList: TripSegment[],
): TransportBuckets {
  const segmentLegs = segmentList.map(segmentToLeg).sort(byDeparture);

  if (flightList.length === 0) {
    return { outbound: segmentLegs, during: [], returning: null, hasFlights: false };
  }

  const { outbound, returning } = splitLegs(flightList);
  const outboundLegs = outbound.map(flightToLeg);
  const returningLegs = returning ? returning.map(flightToLeg) : null;

  // End of the journey out, and start of the journey home. A segment departing
  // between the two is "during".
  const outboundEnd = Math.max(
    ...outboundLegs.map((l) => {
      const iso = l.arrival_datetime ?? l.departure_datetime;
      const t = iso ? new Date(iso).getTime() : NaN;
      return isNaN(t) ? -Infinity : t;
    }),
  );
  const returnStart = returningLegs
    ? Math.min(...returningLegs.map(departureInstant))
    : Number.POSITIVE_INFINITY;

  const during: TransportLeg[] = [];
  for (const leg of segmentLegs) {
    const at = departureInstant(leg);
    if (at < outboundEnd) outboundLegs.push(leg);
    else if (at >= returnStart && returningLegs) returningLegs.push(leg);
    else during.push(leg);
  }

  outboundLegs.sort(byDeparture);
  returningLegs?.sort(byDeparture);

  return {
    outbound: outboundLegs,
    during,
    returning: returningLegs,
    hasFlights: true,
  };
}

// ---- Leg / connection logic ----

export interface LegStats {
  flyingMinutes: number;
  totalMinutes: number;
}

export function legStats(legList: TransportLeg[]): LegStats {
  const flyingMinutes = legList.reduce((sum, l) => sum + (l.duration_minutes ?? 0), 0);

  const MAX_STOPOVER_MS = 24 * 60 * 60 * 1000;
  let hasLongStopover = false;

  for (let i = 1; i < legList.length; i++) {
    const prev = new Date(
      legList[i - 1].arrival_datetime ?? legList[i - 1].departure_datetime ?? 0
    );
    const curr = new Date(legList[i].departure_datetime ?? 0);
    if (curr.getTime() - prev.getTime() > MAX_STOPOVER_MS) {
      hasLongStopover = true;
      break;
    }
  }

  let totalMinutes = 0;
  if (!hasLongStopover && legList.length > 0) {
    const first = legList[0];
    const last = legList[legList.length - 1];
    if (first.departure_datetime && last.arrival_datetime) {
      const ms = new Date(last.arrival_datetime).getTime() - new Date(first.departure_datetime).getTime();
      totalMinutes = Math.round(ms / 60000);
    }
  }

  return { flyingMinutes, totalMinutes };
}

export interface SplitLegs {
  outbound: Flight[];
  returning: Flight[] | null;
}

/**
 * Split a flight list into the journey out and the journey home.
 *
 * "Did we come home" is decided from the flights themselves — last arrival
 * airport equals first departure airport — not from `trip.origin_airport` /
 * `trip.destination_airport`. Those two fields disagree about what they mean:
 * the backend sets destination to the *final arrival*, which for a round trip
 * is the origin, so keying off them meant a genuine FRA→PEK→FRA trip compared
 * equal and never split. That is the one case the split exists for.
 *
 * A one-way with a long layover still must not split, which is what the
 * came-home test buys over the 12h gap alone.
 */
export function splitLegs(flightList: Flight[]): SplitLegs {
  if (flightList.length < 2) {
    return { outbound: flightList, returning: null };
  }

  const startedAt = flightList[0].departure_airport;
  const endedAt = flightList[flightList.length - 1].arrival_airport;
  if (!startedAt || !endedAt || startedAt !== endedAt) {
    return { outbound: flightList, returning: null };
  }

  let maxGap = 0;
  let returnIndex = -1;

  for (let i = 1; i < flightList.length; i++) {
    const prev = new Date(
      flightList[i - 1].arrival_datetime ?? flightList[i - 1].departure_datetime ?? 0
    ).getTime();
    const curr = new Date(flightList[i].departure_datetime ?? 0).getTime();
    const gap = curr - prev;
    if (gap > maxGap) {
      maxGap = gap;
      returnIndex = i;
    }
  }

  const TWELVE_HOURS = 12 * 60 * 60 * 1000;
  if (returnIndex > 0 && maxGap >= TWELVE_HOURS) {
    return {
      outbound: flightList.slice(0, returnIndex),
      returning: flightList.slice(returnIndex),
    };
  }

  return { outbound: flightList, returning: null };
}

export interface ConnectionInfo {
  gapMin: number;
  label: string;
  /** Where the wait happens — an IATA code between flights, a station name
   * when a ground leg is involved. */
  place: string;
}

export function connectionInfo(prev: TransportLeg, next: TransportLeg): ConnectionInfo | null {
  if (!prev.arrival_datetime || !next.departure_datetime) return null;
  const gapMs = new Date(next.departure_datetime).getTime() - new Date(prev.arrival_datetime).getTime();
  if (gapMs <= 0) return null;
  const gapMin = Math.round(gapMs / 60000);
  const h = Math.floor(gapMin / 60);
  const m = gapMin % 60;
  const label = h > 0 ? `${h}h ${m}m` : `${m}m`;
  return { gapMin, label, place: prev.arrival_place };
}

export interface DateDividerInfo {
  label: string;
  crossesDay: boolean;
}

export function dateDividerInfo(prev: TransportLeg, next: TransportLeg): DateDividerInfo | null {
  const prevDate = (prev.arrival_datetime ?? prev.departure_datetime ?? '').slice(0, 10);
  const nextDate = (next.departure_datetime ?? '').slice(0, 10);
  if (!prevDate || !nextDate || prevDate === nextDate) return null;

  const dep = next.departure_datetime;
  if (!dep) return null;
  const d = new Date(dep);
  const tz = next.departure_timezone;
  let label: string;
  try {
    label = d.toLocaleDateString(appLocale(), {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      ...(tz ? { timeZone: tz } : {}),
    });
  } catch {
    label = dep.slice(0, 10);
  }
  return { label, crossesDay: true };
}

// ---------------------------------------------------------------------------
// Stays
//
// Everything below works on `YYYY-MM-DD` date *keys*, never on Date objects
// built from the stored instants. A stay's identity is its local calendar dates
// at the property — "14-18 October" — and the backend already resolved those
// into `check_in_date` / `check_out_date`. Re-deriving them in the browser would
// reintroduce exactly the bug those columns exist to prevent: a 15:00 check-in
// at UTC-10 is the next day in UTC, and a viewer in a third timezone gets a
// third answer.
// ---------------------------------------------------------------------------

const DAY_MS = 86_400_000;

function dateKeyToUtcMs(key: string): number {
  const [y, m, d] = key.split('-').map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Whole days from `a` to `b`, both `YYYY-MM-DD`. Negative when `b` precedes `a`. */
export function daysBetweenDateKeys(a: string, b: string): number {
  return Math.round((dateKeyToUtcMs(b) - dateKeyToUtcMs(a)) / DAY_MS);
}

export function addDaysToDateKey(key: string, days: number): string {
  return new Date(dateKeyToUtcMs(key) + days * DAY_MS).toISOString().slice(0, 10);
}

/** The number of nights a stay covers, falling back to its own dates when the
 * backend did not supply the count. */
export function stayNightCount(stay: TripStay): number {
  return stay.nights ?? daysBetweenDateKeys(stay.check_in_date, stay.check_out_date);
}

export interface StayNight {
  stay: TripStay;
  /** 1-based night number within this stay, for "night 2 of 4". */
  night: number;
  nights: number;
}

export interface StayDay {
  /** Stays whose *night* falls on this day. */
  nights: StayNight[];
  checkIns: TripStay[];
  checkOuts: TripStay[];
}

/**
 * What a given planner day should show for accommodation.
 *
 * A stay covers the **night of** every date from check-in up to, but excluding,
 * check-out — you sleep at the property on the 4th through the 7th for a 4-8
 * October booking, and on the 8th you are already leaving. Check-out therefore
 * gets an entry on its own day without that day counting as a night.
 */
/**
 * Per-currency totals as display strings: `{ EUR: 420, SEK: 900 }` →
 * `["EUR 420", "SEK 900"]`.
 *
 * Currencies are sorted so the order does not depend on insertion, and a whole
 * number keeps no decimals — "EUR 420,00" is noise on a summary line, while
 * "EUR 420,50" needs both places.
 */
export function formatCurrencyTotals(totals: Record<string, number> | undefined): string[] {
  return Object.entries(totals ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, total]) => {
      const amount =
        total % 1 === 0
          ? total.toLocaleString()
          : total.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            });
      return `${currency} ${amount}`;
    });
}

/** One line of a trip's inventory: a glyph, a count, and the key that names it. */
export interface TripContentPart {
  icon: string;
  labelKey: string;
  count: number;
}

const SEGMENT_ICONS: Record<string, string> = {
  train: '🚆',
  bus: '🚌',
  ferry: '⛴️',
  car: '🚗',
};

/** Fixed glyph order, so the summary reads the same between renders rather
 *  than following whatever order the rows came back in. */
const SEGMENT_ORDER = ['train', 'bus', 'ferry', 'car'];

/**
 * What a trip actually holds, broken down by kind: "2 flights · 1 ferry ·
 * 2 drives · 3 stays".
 *
 * The trip card computes a coarser version of this — a mixed trip there says
 * "3 legs", because the card is a glance and has only per-kind *counts*, not
 * the rows. Inside the trip the rows are loaded, so each kind can be named:
 * "0 flights" on a road trip is true and useless, and so is "3 legs" when you
 * are looking at the page that lists them.
 *
 * Zero-count kinds are omitted entirely; an empty trip returns `[]` and the
 * caller shows nothing rather than a row of noughts.
 */
export function tripContents(
  flightCount: number,
  segmentTypes: string[],
  stayCount: number,
): TripContentPart[] {
  const parts: TripContentPart[] = [];

  if (flightCount > 0) {
    parts.push({ icon: '✈', labelKey: 'trips.flight_count', count: flightCount });
  }

  const counts = new Map<string, number>();
  for (const type of segmentTypes) {
    counts.set(type, (counts.get(type) ?? 0) + 1);
  }
  // Known kinds first, in their fixed order; anything unrecognised keeps a
  // neutral glyph and the generic label rather than being guessed at.
  for (const type of SEGMENT_ORDER) {
    const count = counts.get(type);
    if (count) {
      parts.push({ icon: SEGMENT_ICONS[type], labelKey: `trips.segment_count_${type}`, count });
    }
    counts.delete(type);
  }
  const unknown = [...counts.values()].reduce((a, b) => a + b, 0);
  if (unknown > 0) {
    parts.push({ icon: '↔', labelKey: 'trips.segment_count', count: unknown });
  }

  if (stayCount > 0) {
    parts.push({ icon: '🛏', labelKey: 'trips.stay_count', count: stayCount });
  }

  return parts;
}

/**
 * The local calendar date at a place for an instant stored as UTC.
 *
 * A leg belongs to the day it happens *locally*, not in UTC: an 08:00 Beijing
 * departure is 00:00Z and would land on the right day only by luck.
 */
export function localDateKey(
  iso: string | null | undefined,
  timezone?: string | null,
): string | null {
  if (!iso) return null;
  try {
    // en-CA gives ISO-ordered parts, so the result is already a sortable key.
    return new Date(iso).toLocaleDateString('en-CA', {
      timeZone: timezone ?? undefined,
    });
  } catch {
    return iso.slice(0, 10);
  }
}

/** What a leg is doing on a given day. */
export type LegRole = 'departs' | 'arrives' | 'transit';

/**
 * Where a day sits inside a leg that may span several of them.
 *
 * A drive leaving on the 31st and arriving on the 1st used to be filed on the
 * 31st alone, so the day spent on the road showed nothing at all — and the
 * planner draws one card per day precisely so no day of a trip is blank.
 *
 * `to` missing, or before `from` (which a mistyped year produces), degrades to
 * a single-day leg rather than an empty or backwards range.
 */
export function legRoleFor(
  date: string,
  from: string | null,
  to: string | null,
): LegRole | null {
  if (!from) return null;
  const end = to && to > from ? to : from;
  if (date === from) return 'departs';
  if (date === end) return 'arrives';
  return date > from && date < end ? 'transit' : null;
}

/** Every local date a leg touches, departure day through arrival day. */
export function legDateKeys(from: string | null, to: string | null): string[] {
  if (!from) return [];
  const end = to && to > from ? to : from;
  const keys: string[] = [];
  const [fy, fm, fd] = from.split('-').map(Number);
  const cur = new Date(fy, fm - 1, fd);
  // A leg longer than this is a data error, not a journey; the cap stops a
  // mistyped year from generating decades of day cards.
  for (let i = 0; i < 366; i++) {
    const key = `${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, '0')}-${String(cur.getDate()).padStart(2, '0')}`;
    keys.push(key);
    if (key >= end) break;
    cur.setDate(cur.getDate() + 1);
  }
  return keys;
}

export function staysForDay(stays: TripStay[], date: string): StayDay {
  const nights: StayNight[] = [];
  const checkIns: TripStay[] = [];
  const checkOuts: TripStay[] = [];

  for (const stay of stays) {
    if (stay.check_in_date === date) checkIns.push(stay);
    if (stay.check_out_date === date) checkOuts.push(stay);
    if (date >= stay.check_in_date && date < stay.check_out_date) {
      nights.push({
        stay,
        night: daysBetweenDateKeys(stay.check_in_date, date) + 1,
        nights: stayNightCount(stay),
      });
    }
  }

  return { nights, checkIns, checkOuts };
}

/**
 * Nights in the trip's span with no accommodation booked, as date keys.
 *
 * The last day of a trip is not a night — you leave that morning — so the range
 * checked stops one day short of `endDate`. Returns `[]` when the trip has no
 * span yet, or no stays at all: "every night is missing" is not a useful thing
 * to tell someone who has not started booking.
 */
export function accommodationGaps(
  stays: TripStay[],
  startDate: string | null | undefined,
  endDate: string | null | undefined,
): string[] {
  if (!startDate || !endDate || stays.length === 0) return [];

  const gaps: string[] = [];
  const lastNight = daysBetweenDateKeys(startDate, endDate) - 1;
  for (let offset = 0; offset <= lastNight; offset++) {
    const date = addDaysToDateKey(startDate, offset);
    const covered = stays.some((s) => date >= s.check_in_date && date < s.check_out_date);
    if (!covered) gaps.push(date);
  }
  return gaps;
}

/**
 * Whether a stay falls outside the trip's transport, and how.
 *
 * This drives a *warning*, never a rejection — the trip's end date is derived
 * from the stays themselves (`TripRepository._recompute_span`), so a check-out
 * past the last leg is not an error to refuse; it moves the end of the trip.
 * Three outcomes:
 *
 *   'before'   — the stay ends before any transport starts
 *   'after'    — the stay starts after all transport has ended
 *   'overruns' — the stay overlaps the transport but its check-out runs past
 *                the last arrival, i.e. a night at the destination after the
 *                journey home: usually a leg not yet added, or a mistyped date
 *
 * Deliberately asymmetric: a check-out running past the last leg is flagged,
 * a check-in falling before the first one is not. The night before an early
 * departure is the standard airport-hotel booking, and warning on it would fire
 * on ordinary trips — nobody reads a warning that is usually wrong.
 *
 * The transport range is read off the stored UTC instants rather than local
 * dates, which can be a day out at the edges. That is deliberate: this answers
 * "is this booking in the wrong month?", and a day of slack costs nothing.
 */
export function stayOutsideTravel(
  stay: TripStay,
  flights: Flight[],
  segments: TripSegment[],
): 'before' | 'after' | 'overruns' | null {
  const dates = [
    ...flights.flatMap((f) => [f.departure_datetime, f.arrival_datetime]),
    ...segments.flatMap((s) => [s.departure_datetime, s.arrival_datetime]),
  ]
    .filter((d): d is string => Boolean(d))
    .map((d) => d.slice(0, 10))
    .sort();

  if (dates.length === 0) return null;

  const first = dates[0];
  const last = dates[dates.length - 1];
  if (stay.check_out_date < first) return 'before';
  // Checked before 'overruns', which is also true of a stay entirely after the
  // transport: the more specific message wins.
  if (stay.check_in_date > last) return 'after';
  if (stay.check_out_date > last) return 'overruns';
  return null;
}
