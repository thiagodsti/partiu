/**
 * Shared utility functions used across pages.
 * Ported from the vanilla JS page files.
 */

import type { Flight, Trip } from '../api/types';

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
  if (trip.end_date && new Date(trip.end_date) < now) return 'completed';
  if (trip.start_date && new Date(trip.start_date) <= now) return 'ongoing';
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

// ---- Leg / connection logic ----

export interface LegStats {
  flyingMinutes: number;
  totalMinutes: number;
}

export function legStats(flightList: Flight[]): LegStats {
  const flyingMinutes = flightList.reduce((sum, f) => sum + (f.duration_minutes ?? 0), 0);

  const MAX_STOPOVER_MS = 24 * 60 * 60 * 1000;
  let hasLongStopover = false;

  for (let i = 1; i < flightList.length; i++) {
    const prev = new Date(
      flightList[i - 1].arrival_datetime ?? flightList[i - 1].departure_datetime ?? 0
    );
    const curr = new Date(flightList[i].departure_datetime ?? 0);
    if (curr.getTime() - prev.getTime() > MAX_STOPOVER_MS) {
      hasLongStopover = true;
      break;
    }
  }

  let totalMinutes = 0;
  if (!hasLongStopover && flightList.length > 0) {
    const first = flightList[0];
    const last = flightList[flightList.length - 1];
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

export function splitLegs(flightList: Flight[], trip: Trip): SplitLegs {
  if (flightList.length < 2 || trip.origin_airport === trip.destination_airport) {
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
  airport: string;
}

export function connectionInfo(prev: Flight, next: Flight): ConnectionInfo | null {
  if (!prev.arrival_datetime || !next.departure_datetime) return null;
  const gapMs = new Date(next.departure_datetime).getTime() - new Date(prev.arrival_datetime).getTime();
  if (gapMs <= 0) return null;
  const gapMin = Math.round(gapMs / 60000);
  const h = Math.floor(gapMin / 60);
  const m = gapMin % 60;
  const label = h > 0 ? `${h}h ${m}m` : `${m}m`;
  return { gapMin, label, airport: prev.arrival_airport ?? '' };
}

export interface DateDividerInfo {
  label: string;
  crossesDay: boolean;
}

export function dateDividerInfo(prevFlight: Flight, nextFlight: Flight): DateDividerInfo | null {
  const prevDate = (prevFlight.arrival_datetime ?? prevFlight.departure_datetime ?? '').slice(0, 10);
  const nextDate = (nextFlight.departure_datetime ?? '').slice(0, 10);
  if (!prevDate || !nextDate || prevDate === nextDate) return null;

  const dep = nextFlight.departure_datetime;
  if (!dep) return null;
  const d = new Date(dep);
  const tz = nextFlight.departure_timezone;
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
