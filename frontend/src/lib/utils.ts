/**
 * Shared utility functions used across pages.
 * Ported from the vanilla JS page files.
 */

import type { Flight, TripSegment } from '../api/types';

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
