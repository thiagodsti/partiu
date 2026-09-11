import { describe, it, expect } from 'vitest';
import type { Flight, TripSegment } from '../api/types';
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
  toLocalInputValue,
  flightToLeg,
  segmentToLeg,
  splitTransport,
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

function localDateStr(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

describe('inferTripStatus', () => {
  it('returns completed when end date is in the past', () => {
    expect(inferTripStatus({ end_date: '2020-01-01' })).toBe('completed');
  });

  it('returns ongoing when end date is today (not completed until end of day)', () => {
    expect(inferTripStatus({ start_date: localDateStr(-1), end_date: localDateStr(0) })).toBe('ongoing');
  });

  it('returns ongoing when start is past and end is future', () => {
    expect(inferTripStatus({ start_date: localDateStr(-1), end_date: localDateStr(1) })).toBe('ongoing');
  });

  it('returns upcoming when start date is in the future', () => {
    expect(inferTripStatus({ start_date: localDateStr(1) })).toBe('upcoming');
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
    const prev = flightToLeg(makeFlight({ arrival_datetime: undefined }));
    const next = flightToLeg(makeFlight({ departure_datetime: '2024-06-01T16:00:00Z' }));
    expect(connectionInfo(prev, next)).toBeNull();
  });

  it('returns null when gap is zero or negative', () => {
    const prev = flightToLeg(makeFlight({ arrival_datetime: '2024-06-01T14:00:00Z' }));
    const next = flightToLeg(makeFlight({ departure_datetime: '2024-06-01T14:00:00Z' }));
    expect(connectionInfo(prev, next)).toBeNull();
  });

  it('calculates layover correctly', () => {
    const prev = flightToLeg(makeFlight({ arrival_datetime: '2024-06-01T14:00:00Z', arrival_airport: 'LIM' }));
    const next = flightToLeg(makeFlight({ departure_datetime: '2024-06-01T16:30:00Z' }));
    const info = connectionInfo(prev, next);
    expect(info).not.toBeNull();
    expect(info!.gapMin).toBe(150);
    expect(info!.label).toBe('2h 30m');
    expect(info!.place).toBe('LIM');
  });

  it('formats sub-hour layover as minutes only', () => {
    const prev = flightToLeg(makeFlight({ arrival_datetime: '2024-06-01T14:00:00Z' }));
    const next = flightToLeg(makeFlight({ departure_datetime: '2024-06-01T14:45:00Z' }));
    const info = connectionInfo(prev, next);
    expect(info!.label).toBe('45m');
  });
});

// ---- splitLegs ----

describe('splitLegs', () => {
  it('returns single outbound leg for one flight', () => {
    const result = splitLegs([makeFlight()]);
    expect(result.outbound).toHaveLength(1);
    expect(result.returning).toBeNull();
  });

  it('does not split a one-way trip that never comes home', () => {
    // GRU → SCL twice: the traveller never returns to GRU, so a long gap
    // between the legs is a stopover, not a return.
    const flights = [
      makeFlight({ id: 'f1', arrival_datetime: '2024-06-01T14:00:00Z' }),
      makeFlight({ id: 'f2', departure_datetime: '2024-06-07T10:00:00Z' }),
    ];
    expect(splitLegs(flights).returning).toBeNull();
  });

  it('splits a real round trip, where the final arrival is the origin', () => {
    // The case the old origin-vs-destination guard got backwards: a genuine
    // FRA → PEK → FRA trip has origin === destination and never split.
    const out = makeFlight({
      id: 'out',
      departure_airport: 'FRA',
      arrival_airport: 'PEK',
      departure_datetime: '2024-06-01T08:00:00Z',
      arrival_datetime: '2024-06-01T20:00:00Z',
    });
    const back = makeFlight({
      id: 'back',
      departure_airport: 'PEK',
      arrival_airport: 'FRA',
      departure_datetime: '2024-06-14T08:00:00Z',
      arrival_datetime: '2024-06-14T20:00:00Z',
    });
    const result = splitLegs([out, back]);
    expect(result.outbound.map((f) => f.id)).toEqual(['out']);
    expect(result.returning?.map((f) => f.id)).toEqual(['back']);
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
    const result = splitLegs([f1, f2]);
    expect(result.outbound).toHaveLength(1);
    expect(result.returning).toHaveLength(1);
  });

  it('does not split when gap is less than 12h', () => {
    // Comes home (GRU → SCL → GRU) but turns straight around: a 2h gap is a
    // connection, not the middle of a trip.
    const f1 = makeFlight({ id: 'f1', arrival_datetime: '2024-06-01T14:00:00Z' });
    const f2 = makeFlight({
      id: 'f2',
      departure_airport: 'SCL',
      arrival_airport: 'GRU',
      departure_datetime: '2024-06-01T16:00:00Z',
    });
    expect(splitLegs([f1, f2]).returning).toBeNull();
  });
});

// ---- legStats ----

describe('legStats', () => {
  it('sums flight durations', () => {
    const flights = [
      makeFlight({ duration_minutes: 90 }),
      makeFlight({ id: 'f2', duration_minutes: 120 }),
    ];
    const stats = legStats(flights.map(flightToLeg));
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
    const stats = legStats(flights.map(flightToLeg));
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
    const prev = flightToLeg(makeFlight({ arrival_datetime: '2024-06-01T23:00:00Z' }));
    const next = flightToLeg(makeFlight({ departure_datetime: '2024-06-01T10:00:00Z' }));
    expect(dateDividerInfo(prev, next)).toBeNull();
  });

  it('returns divider info when flights cross a date boundary', () => {
    const prev = flightToLeg(makeFlight({ arrival_datetime: '2024-06-01T23:00:00Z' }));
    const next = flightToLeg(makeFlight({ departure_datetime: '2024-06-02T08:00:00Z' }));
    const info = dateDividerInfo(prev, next);
    expect(info).not.toBeNull();
    expect(info!.crossesDay).toBe(true);
    expect(info!.label).toBeTruthy();
  });

  it('returns null when next departure datetime is missing', () => {
    const prev = flightToLeg(makeFlight({ arrival_datetime: '2024-06-01T23:00:00Z' }));
    const next = flightToLeg(makeFlight({ departure_datetime: undefined }));
    expect(dateDividerInfo(prev, next)).toBeNull();
  });
});

// ---- splitTransport ----

function makeSegment(overrides: Partial<TripSegment> = {}): TripSegment {
  return {
    id: 's1',
    trip_id: 't1',
    type: 'train',
    operator: 'China Railway',
    number: 'G87',
    booking_reference: null,
    departure: { name: 'Beijing West', lat: 39.89, lon: 116.31, timezone: 'Asia/Shanghai' },
    departure_datetime: '2024-06-05T00:00:00Z',
    arrival: { name: "Xi'an North", lat: 34.37, lon: 108.93, timezone: 'Asia/Shanghai' },
    arrival_datetime: '2024-06-05T04:30:00Z',
    duration_minutes: 270,
    seat: null,
    notes: null,
    created_by: null,
    created_by_username: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

/** Out on the 1st, back on the 10th — the shape splitLegs needs to find a
 * return (>=12h gap, and origin !== destination on the trip). */
function roundTripFlights(): Flight[] {
  return [
    makeFlight({
      id: 'out',
      departure_airport: 'FRA',
      arrival_airport: 'PEK',
      departure_datetime: '2024-06-01T08:00:00Z',
      arrival_datetime: '2024-06-01T20:00:00Z',
    }),
    makeFlight({
      id: 'back',
      departure_airport: 'PEK',
      arrival_airport: 'FRA',
      departure_datetime: '2024-06-10T08:00:00Z',
      arrival_datetime: '2024-06-10T20:00:00Z',
    }),
  ];
}

describe('splitTransport', () => {
  it('puts a segment between the flights in the middle bucket', () => {
    const result = splitTransport(roundTripFlights(), [makeSegment()]);
    expect(result.hasFlights).toBe(true);
    expect(result.outbound.map((l) => l.id)).toEqual(['flight-out']);
    expect(result.during.map((l) => l.id)).toEqual(['segment-s1']);
    expect(result.returning?.map((l) => l.id)).toEqual(['flight-back']);
  });

  it('attaches a segment before the outbound arrival to the outbound leg', () => {
    // A train to the airport, departing before the outbound flight lands.
    const toAirport = makeSegment({
      id: 'pre',
      departure_datetime: '2024-06-01T05:00:00Z',
      arrival_datetime: '2024-06-01T06:00:00Z',
    });
    const result = splitTransport(roundTripFlights(), [toAirport]);
    expect(result.outbound.map((l) => l.id)).toEqual(['segment-pre', 'flight-out']);
    expect(result.during).toHaveLength(0);
  });

  it('attaches a segment after the return departure to the return leg', () => {
    const fromAirport = makeSegment({
      id: 'post',
      departure_datetime: '2024-06-10T21:00:00Z',
      arrival_datetime: '2024-06-10T22:00:00Z',
    });
    const result = splitTransport(roundTripFlights(), [fromAirport]);
    expect(result.during).toHaveLength(0);
    expect(result.returning?.map((l) => l.id)).toEqual(['flight-back', 'segment-post']);
  });

  it('treats everything after the last flight as during when there is no return', () => {
    const oneWay = [
      makeFlight({
        id: 'out',
        departure_airport: 'FRA',
        arrival_airport: 'PEK',
        departure_datetime: '2024-06-01T08:00:00Z',
        arrival_datetime: '2024-06-01T20:00:00Z',
      }),
    ];
    const result = splitTransport(oneWay, [makeSegment()]);
    expect(result.returning).toBeNull();
    expect(result.outbound.map((l) => l.id)).toEqual(['flight-out']);
    expect(result.during.map((l) => l.id)).toEqual(['segment-s1']);
  });

  it('drops the outbound/return framing entirely when there are no flights', () => {
    const result = splitTransport([], [makeSegment()]);
    expect(result.hasFlights).toBe(false);
    expect(result.during).toHaveLength(0);
    expect(result.returning).toBeNull();
    expect(result.outbound.map((l) => l.id)).toEqual(['segment-s1']);
  });

  it('orders the middle bucket by departure regardless of input order', () => {
    const later = makeSegment({ id: 'b', departure_datetime: '2024-06-07T00:00:00Z' });
    const earlier = makeSegment({ id: 'a', departure_datetime: '2024-06-03T00:00:00Z' });
    const result = splitTransport(roundTripFlights(), [later, earlier]);
    expect(result.during.map((l) => l.id)).toEqual(['segment-a', 'segment-b']);
  });

  it('leaves a flights-only trip exactly as splitLegs had it', () => {
    const result = splitTransport(roundTripFlights(), []);
    expect(result.outbound.map((l) => l.id)).toEqual(['flight-out']);
    expect(result.during).toHaveLength(0);
    expect(result.returning?.map((l) => l.id)).toEqual(['flight-back']);
  });
});

// ---- leg adapters ----

describe('segmentToLeg', () => {
  it('exposes station names as the place labels', () => {
    const leg = segmentToLeg(makeSegment());
    expect(leg.kind).toBe('segment');
    expect(leg.departure_place).toBe('Beijing West');
    expect(leg.arrival_place).toBe("Xi'an North");
    expect(leg.segment).toBeDefined();
  });

  it('feeds connectionInfo a station name rather than an IATA code', () => {
    // The layover between landing and boarding a train is a real connection,
    // and naming it "PEK" would be wrong on the train side.
    const arrive = flightToLeg(
      makeFlight({ arrival_airport: 'PEK', arrival_datetime: '2024-06-05T00:00:00Z' }),
    );
    const train = segmentToLeg(makeSegment({ departure_datetime: '2024-06-05T03:00:00Z' }));
    expect(connectionInfo(arrive, train)!.place).toBe('PEK');
    expect(connectionInfo(train, arrive)).toBeNull(); // train arrives after
  });
});

describe('flightToLeg', () => {
  it('exposes IATA codes as the place labels', () => {
    const leg = flightToLeg(makeFlight({ departure_airport: 'GRU', arrival_airport: 'LIM' }));
    expect(leg.kind).toBe('flight');
    expect(leg.departure_place).toBe('GRU');
    expect(leg.arrival_place).toBe('LIM');
    expect(leg.flight).toBeDefined();
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

describe('toLocalInputValue', () => {
  it('renders a UTC instant as wall-clock time at the given zone', () => {
    // A G87 leaving Beijing West at 08:00 local is stored as 00:00Z; the edit
    // form has to show 08:00 again regardless of where the browser is.
    expect(toLocalInputValue('2026-10-04T00:00:00+00:00', 'Asia/Shanghai')).toBe('2026-10-04T08:00');
  });

  it('rolls the date when the zone offset crosses midnight', () => {
    expect(toLocalInputValue('2026-10-03T20:00:00+00:00', 'Asia/Shanghai')).toBe('2026-10-04T04:00');
  });

  it('handles a zone behind UTC', () => {
    expect(toLocalInputValue('2026-10-04T02:00:00+00:00', 'America/Sao_Paulo')).toBe('2026-10-03T23:00');
  });

  it('produces a value a datetime-local input accepts', () => {
    expect(toLocalInputValue('2026-10-04T00:00:00+00:00', 'Europe/Paris')).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/,
    );
  });

  it('returns an empty string for missing input', () => {
    expect(toLocalInputValue(null, 'Asia/Shanghai')).toBe('');
    expect(toLocalInputValue(undefined, 'Asia/Shanghai')).toBe('');
    expect(toLocalInputValue('', 'Asia/Shanghai')).toBe('');
  });

  it('returns an empty string for an unparseable value', () => {
    expect(toLocalInputValue('not-a-date', 'Asia/Shanghai')).toBe('');
  });

  it('falls back to the browser zone when no timezone is given', () => {
    // A place the geocoder could not match has no stored zone; the value must
    // still be well-formed rather than blank.
    expect(toLocalInputValue('2026-10-04T08:00:00+00:00', null)).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/,
    );
  });
});
