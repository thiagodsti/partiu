import { describe, it, expect } from 'vitest';
import type { Flight, Trip } from '../api/types';
import {
  escapeHtml,
  formatDuration,
  formatDateRange,
  cabinLabel,
  flightStatus,
  inferTripStatus,
  timeUntilTrip,
  seatMapUrl,
  splitLegs,
  connectionInfo,
  legStats,
  dateDividerInfo,
} from './utils';

// ---- helpers ----

function makeFlight(overrides: Partial<Flight> = {}): Flight {
  return {
    id: 'f1',
    trip_id: 't1',
    flight_number: 'LA100',
    departure_airport: 'GRU',
    arrival_airport: 'SCL',
    departure_datetime: '2024-06-01T10:00:00Z',
    arrival_datetime: '2024-06-01T14:00:00Z',
    duration_minutes: 240,
    airline_code: 'LA',
    status: 'upcoming',
    ...overrides,
  } as Flight;
}

function makeTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 't1',
    name: 'Test Trip',
    origin_airport: 'GRU',
    destination_airport: 'SCL',
    start_date: '2024-06-01',
    end_date: '2024-06-10',
    flights: [],
    ...overrides,
  } as Trip;
}

// ---- escapeHtml ----

describe('escapeHtml', () => {
  it('escapes angle brackets', () => {
    expect(escapeHtml('<b>hello</b>')).toBe('&lt;b&gt;hello&lt;/b&gt;');
  });

  it('escapes ampersands', () => {
    expect(escapeHtml('a & b')).toBe('a &amp; b');
  });

  it('escapes double quotes', () => {
    expect(escapeHtml('"quoted"')).toBe('&quot;quoted&quot;');
  });

  it('returns empty string for null', () => {
    expect(escapeHtml(null)).toBe('');
  });

  it('coerces numbers', () => {
    expect(escapeHtml(42)).toBe('42');
  });
});

// ---- formatDuration ----

describe('formatDuration', () => {
  it('returns null for null input', () => {
    expect(formatDuration(null)).toBeNull();
  });

  it('returns null for zero', () => {
    expect(formatDuration(0)).toBeNull();
  });

  it('formats minutes only', () => {
    expect(formatDuration(45)).toBe('45m');
  });

  it('formats hours and minutes', () => {
    expect(formatDuration(125)).toBe('2h 5m');
  });

  it('formats exact hours', () => {
    expect(formatDuration(120)).toBe('2h 0m');
  });
});

// ---- formatDateRange ----

describe('formatDateRange', () => {
  it('returns empty string when no start date', () => {
    expect(formatDateRange(null, null)).toBe('');
  });

  it('returns single date when no end date', () => {
    const result = formatDateRange('2024-06-01', null);
    expect(result).toBeTruthy();
    expect(result).not.toContain('–');
  });

  it('returns single date when start equals end', () => {
    const result = formatDateRange('2024-06-01', '2024-06-01');
    expect(result).not.toContain('–');
  });

  it('returns range with dash when dates differ', () => {
    const result = formatDateRange('2024-06-01', '2024-06-10');
    expect(result).toContain('–');
  });
});

// ---- cabinLabel ----

describe('cabinLabel', () => {
  it('maps economy', () => {
    expect(cabinLabel('economy')).toBe('Economy');
  });

  it('maps business', () => {
    expect(cabinLabel('business')).toBe('Business');
  });

  it('maps premium_economy', () => {
    expect(cabinLabel('premium_economy')).toBe('Premium Economy');
  });

  it('maps first', () => {
    expect(cabinLabel('first')).toBe('First Class');
  });

  it('returns dash for null', () => {
    expect(cabinLabel(null)).toBe('—');
  });

  it('returns unknown value as-is', () => {
    expect(cabinLabel('charter')).toBe('charter');
  });
});

// ---- flightStatus ----

describe('flightStatus', () => {
  it('returns completed for past arrival', () => {
    const f = makeFlight({ arrival_datetime: '2020-01-01T10:00:00Z' });
    expect(flightStatus(f)).toBe('completed');
  });

  it('returns active for past departure but future arrival', () => {
    const past = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const future = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    const f = makeFlight({ departure_datetime: past, arrival_datetime: future });
    expect(flightStatus(f)).toBe('active');
  });

  it('returns upcoming for future departure', () => {
    const future = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
    const f = makeFlight({ departure_datetime: future, arrival_datetime: undefined });
    expect(flightStatus(f)).toBe('upcoming');
  });
});

// ---- inferTripStatus ----

describe('inferTripStatus', () => {
  it('returns completed when end date is in the past', () => {
    expect(inferTripStatus({ end_date: '2020-01-01' })).toBe('completed');
  });

  it('returns ongoing when end date is today (not completed until end of day)', () => {
    const today = new Date().toISOString().slice(0, 10);
    const past = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    expect(inferTripStatus({ start_date: past, end_date: today })).toBe('ongoing');
  });

  it('returns ongoing when start is past and end is future', () => {
    const past = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    const future = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    expect(inferTripStatus({ start_date: past, end_date: future })).toBe('ongoing');
  });

  it('returns upcoming when start date is in the future', () => {
    const future = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    expect(inferTripStatus({ start_date: future })).toBe('upcoming');
  });

  it('returns upcoming when no dates', () => {
    expect(inferTripStatus({})).toBe('upcoming');
  });
});

// ---- seatMapUrl ----

describe('seatMapUrl', () => {
  it('returns null for null input', () => {
    expect(seatMapUrl(null)).toBeNull();
  });

  it('slugifies the aircraft type', () => {
    const url = seatMapUrl('Boeing 737-800');
    expect(url).toContain('boeing-737-800');
  });

  it('lowercases the type', () => {
    const url = seatMapUrl('AIRBUS A320');
    expect(url).toContain('airbus-a320');
  });
});

// ---- connectionInfo ----

describe('connectionInfo', () => {
  it('returns null when arrival datetime missing', () => {
    const prev = makeFlight({ arrival_datetime: undefined });
    const next = makeFlight({ departure_datetime: '2024-06-01T16:00:00Z' });
    expect(connectionInfo(prev, next)).toBeNull();
  });

  it('returns null when gap is zero or negative', () => {
    const prev = makeFlight({ arrival_datetime: '2024-06-01T14:00:00Z' });
    const next = makeFlight({ departure_datetime: '2024-06-01T14:00:00Z' });
    expect(connectionInfo(prev, next)).toBeNull();
  });

  it('calculates layover correctly', () => {
    const prev = makeFlight({ arrival_datetime: '2024-06-01T14:00:00Z', arrival_airport: 'LIM' });
    const next = makeFlight({ departure_datetime: '2024-06-01T16:30:00Z' });
    const info = connectionInfo(prev, next);
    expect(info).not.toBeNull();
    expect(info!.gapMin).toBe(150);
    expect(info!.label).toBe('2h 30m');
    expect(info!.airport).toBe('LIM');
  });

  it('formats sub-hour layover as minutes only', () => {
    const prev = makeFlight({ arrival_datetime: '2024-06-01T14:00:00Z' });
    const next = makeFlight({ departure_datetime: '2024-06-01T14:45:00Z' });
    const info = connectionInfo(prev, next);
    expect(info!.label).toBe('45m');
  });
});

// ---- splitLegs ----

describe('splitLegs', () => {
  it('returns single outbound leg for one flight', () => {
    const f = makeFlight();
    const trip = makeTrip();
    const result = splitLegs([f], trip);
    expect(result.outbound).toHaveLength(1);
    expect(result.returning).toBeNull();
  });

  it('does not split when origin equals destination', () => {
    const flights = [makeFlight(), makeFlight({ id: 'f2' })];
    const trip = makeTrip({ origin_airport: 'GRU', destination_airport: 'GRU' });
    const result = splitLegs(flights, trip);
    expect(result.returning).toBeNull();
  });

  it('splits outbound and return legs when gap >= 12h', () => {
    const f1 = makeFlight({
      id: 'f1',
      departure_datetime: '2024-06-01T10:00:00Z',
      arrival_datetime: '2024-06-01T14:00:00Z',
    });
    const f2 = makeFlight({
      id: 'f2',
      departure_airport: 'SCL',
      arrival_airport: 'GRU',
      // 6 days after f1 arrival — well over 12h
      departure_datetime: '2024-06-07T10:00:00Z',
      arrival_datetime: '2024-06-07T14:00:00Z',
    });
    const trip = makeTrip({ origin_airport: 'GRU', destination_airport: 'SCL' });
    const result = splitLegs([f1, f2], trip);
    expect(result.outbound).toHaveLength(1);
    expect(result.returning).toHaveLength(1);
  });

  it('does not split when gap is less than 12h', () => {
    const f1 = makeFlight({ id: 'f1', arrival_datetime: '2024-06-01T14:00:00Z' });
    const f2 = makeFlight({ id: 'f2', departure_datetime: '2024-06-01T16:00:00Z' });
    const trip = makeTrip();
    const result = splitLegs([f1, f2], trip);
    expect(result.returning).toBeNull();
  });
});

// ---- legStats ----

describe('legStats', () => {
  it('sums flight durations', () => {
    const flights = [
      makeFlight({ duration_minutes: 90 }),
      makeFlight({ id: 'f2', duration_minutes: 120 }),
    ];
    const stats = legStats(flights);
    expect(stats.flyingMinutes).toBe(210);
  });

  it('calculates total minutes from first dep to last arr', () => {
    const flights = [
      makeFlight({
        id: 'f1',
        departure_datetime: '2024-06-01T10:00:00Z',
        arrival_datetime: '2024-06-01T12:00:00Z',
        duration_minutes: 120,
      }),
      makeFlight({
        id: 'f2',
        departure_datetime: '2024-06-01T13:00:00Z',
        arrival_datetime: '2024-06-01T15:00:00Z',
        duration_minutes: 120,
      }),
    ];
    const stats = legStats(flights);
    expect(stats.totalMinutes).toBe(300); // 10:00 → 15:00
  });

  it('returns zero totalMinutes for empty list', () => {
    expect(legStats([]).flyingMinutes).toBe(0);
    expect(legStats([]).totalMinutes).toBe(0);
  });
});

// ---- dateDividerInfo ----

describe('dateDividerInfo', () => {
  it('returns null when flights are on the same date', () => {
    const prev = makeFlight({ arrival_datetime: '2024-06-01T23:00:00Z' });
    const next = makeFlight({ departure_datetime: '2024-06-01T10:00:00Z' });
    expect(dateDividerInfo(prev, next)).toBeNull();
  });

  it('returns divider info when flights cross a date boundary', () => {
    const prev = makeFlight({ arrival_datetime: '2024-06-01T23:00:00Z' });
    const next = makeFlight({ departure_datetime: '2024-06-02T08:00:00Z' });
    const info = dateDividerInfo(prev, next);
    expect(info).not.toBeNull();
    expect(info!.crossesDay).toBe(true);
    expect(info!.label).toBeTruthy();
  });

  it('returns null when next departure datetime is missing', () => {
    const prev = makeFlight({ arrival_datetime: '2024-06-01T23:00:00Z' });
    const next = makeFlight({ departure_datetime: undefined });
    expect(dateDividerInfo(prev, next)).toBeNull();
  });
});

// ---- timeUntilTrip ----

describe('timeUntilTrip', () => {
  const base = new Date('2024-06-01T12:00:00Z').getTime();

  it('returns empty string when start is in the past', () => {
    const start = new Date('2024-06-01T11:00:00Z').toISOString();
    expect(timeUntilTrip(start, base)).toBe('');
  });

  it('shows minutes when less than 1 hour away', () => {
    const start = new Date(base + 30 * 60_000).toISOString();
    expect(timeUntilTrip(start, base)).toBe('in 30m');
  });

  it('shows hours and minutes when less than 1 day away', () => {
    const start = new Date(base + (3 * 3600 + 20 * 60) * 1000).toISOString();
    expect(timeUntilTrip(start, base)).toBe('in 3h 20m');
  });

  it('shows days and hours', () => {
    const start = new Date(base + (2 * 86400 + 5 * 3600) * 1000).toISOString();
    expect(timeUntilTrip(start, base)).toBe('in 2d 5h');
  });

  it('shows only days when hours is 0', () => {
    const start = new Date(base + 3 * 86400_000).toISOString();
    expect(timeUntilTrip(start, base)).toBe('in 3d');
  });

  it('shows months and days for trips 30+ days away', () => {
    const start = new Date(base + 35 * 86400_000).toISOString();
    expect(timeUntilTrip(start, base)).toBe('in 1mo 5d');
  });

  it('shows only months for trips 60+ days away', () => {
    const start = new Date(base + 65 * 86400_000).toISOString();
    expect(timeUntilTrip(start, base)).toBe('in 2 months');
  });
});
