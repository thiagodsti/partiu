import { describe, it, expect } from 'vitest';
import type { Flight, TripSegment, TripStay } from '../api/types';
import {
  escapeHtml,
  formatDuration,
  formatDate,
  formatDateRange,
  formatDayMonth,
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
  daysBetweenDateKeys,
  addDaysToDateKey,
  stayNightCount,
  staysForDay,
  accommodationGaps,
  stayOutsideTravel,
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

// ---- formatDayMonth ----

describe('formatDayMonth', () => {
  it('returns empty string for a missing date', () => {
    expect(formatDayMonth(null)).toBe('');
    expect(formatDayMonth(undefined)).toBe('');
  });

  it('renders the day and month', () => {
    const result = formatDayMonth('2026-09-26T07:25:00');
    expect(result).toContain('26');
  });

  // The whole reason this exists: the full date runs to "26 de set. de 2026"
  // in pt-BR and overflowed the fixed-width clock column of a transport row.
  it('leaves the year out', () => {
    expect(formatDayMonth('2026-09-26T07:25:00')).not.toContain('2026');
  });

  it('is shorter than the full date it replaces on a row', () => {
    const iso = '2026-09-26T07:25:00';
    expect(formatDayMonth(iso).length).toBeLessThan(formatDate(iso).length);
  });

  it('renders nothing for a value that cannot be parsed', () => {
    expect(formatDayMonth('not-a-date')).toBe('');
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
    departure: { name: 'Beijing West', lat: 39.89, lon: 116.31, timezone: 'Asia/Shanghai', country_code: 'CN' },
    departure_datetime: '2024-06-05T00:00:00Z',
    arrival: { name: "Xi'an North", lat: 34.37, lon: 108.93, timezone: 'Asia/Shanghai', country_code: 'CN' },
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

// ---- Stays ----

function makeStay(overrides: Partial<TripStay> = {}): TripStay {
  return {
    id: 'st1',
    trip_id: 't1',
    kind: 'hotel',
    place: {
      name: 'Hotel Avenida Palace',
      address: 'R. 1º de Dezembro 123',
      lat: 38.71,
      lon: -9.14,
      timezone: 'Europe/Lisbon',
      country_code: 'PT',
    },
    check_in_datetime: '2024-06-04T14:00:00Z',
    check_in_date: '2024-06-04',
    check_out_datetime: '2024-06-08T10:00:00Z',
    check_out_date: '2024-06-08',
    nights: 4,
    booking_reference: 'BK1',
    confirmation: null,
    contact: null,
    room_type: null,
    guests: 2,
    notes: null,
    created_by: null,
    created_by_username: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('date-key arithmetic', () => {
  it('counts whole days between keys', () => {
    expect(daysBetweenDateKeys('2024-06-04', '2024-06-08')).toBe(4);
  });

  it('is negative when the second key is earlier', () => {
    expect(daysBetweenDateKeys('2024-06-08', '2024-06-04')).toBe(-4);
  });

  it('crosses a month boundary', () => {
    expect(daysBetweenDateKeys('2024-06-29', '2024-07-02')).toBe(3);
  });

  it('crosses a DST boundary without drifting', () => {
    // Europe springs forward on 31 March 2024; a naive local-Date subtraction
    // would come back 23 hours short and round to 6.
    expect(daysBetweenDateKeys('2024-03-28', '2024-04-04')).toBe(7);
  });

  it('adds days across a month boundary', () => {
    expect(addDaysToDateKey('2024-06-29', 3)).toBe('2024-07-02');
  });
});

describe('stayNightCount', () => {
  it('uses the backend count when present', () => {
    expect(stayNightCount(makeStay())).toBe(4);
  });

  it('falls back to the stay dates', () => {
    expect(stayNightCount(makeStay({ nights: null }))).toBe(4);
  });
});

describe('staysForDay', () => {
  const stay = makeStay();

  it('counts the check-in day as the first night', () => {
    const day = staysForDay([stay], '2024-06-04');
    expect(day.nights).toHaveLength(1);
    expect(day.nights[0].night).toBe(1);
    expect(day.nights[0].nights).toBe(4);
    expect(day.checkIns).toHaveLength(1);
    expect(day.checkOuts).toHaveLength(0);
  });

  it('numbers a middle night correctly', () => {
    expect(staysForDay([stay], '2024-06-06').nights[0].night).toBe(3);
  });

  it('counts the last night before check-out', () => {
    expect(staysForDay([stay], '2024-06-07').nights[0].night).toBe(4);
  });

  it('does not count the check-out day as a night', () => {
    // You leave that morning: an entry for the check-out, but no night.
    const day = staysForDay([stay], '2024-06-08');
    expect(day.nights).toHaveLength(0);
    expect(day.checkOuts).toHaveLength(1);
  });

  it('ignores days outside the stay', () => {
    expect(staysForDay([stay], '2024-06-03').nights).toHaveLength(0);
    expect(staysForDay([stay], '2024-06-09').nights).toHaveLength(0);
  });

  it('reports both stays on a changeover day', () => {
    const next = makeStay({
      id: 'st2',
      check_in_date: '2024-06-08',
      check_out_date: '2024-06-10',
      nights: 2,
    });
    const day = staysForDay([stay, next], '2024-06-08');
    expect(day.checkOuts.map((s) => s.id)).toEqual(['st1']);
    expect(day.checkIns.map((s) => s.id)).toEqual(['st2']);
    expect(day.nights.map((n) => n.stay.id)).toEqual(['st2']);
  });

  it('handles a day-use booking with no nights', () => {
    const dayUse = makeStay({ check_out_date: '2024-06-04', nights: 0 });
    const day = staysForDay([dayUse], '2024-06-04');
    expect(day.nights).toHaveLength(0);
    expect(day.checkIns).toHaveLength(1);
    expect(day.checkOuts).toHaveLength(1);
  });
});

describe('accommodationGaps', () => {
  it('finds nothing when the stay covers the trip', () => {
    expect(accommodationGaps([makeStay()], '2024-06-04', '2024-06-08')).toEqual([]);
  });

  it('reports uncovered nights in the middle', () => {
    const first = makeStay({ check_out_date: '2024-06-06', nights: 2 });
    const second = makeStay({
      id: 'st2',
      check_in_date: '2024-06-07',
      check_out_date: '2024-06-08',
      nights: 1,
    });
    expect(accommodationGaps([first, second], '2024-06-04', '2024-06-08')).toEqual(['2024-06-06']);
  });

  it('does not treat the last day of the trip as a night', () => {
    // The trip ends on the 8th and the stay ends on the 8th: nothing missing.
    expect(accommodationGaps([makeStay()], '2024-06-04', '2024-06-08')).toEqual([]);
  });

  it('reports a night before the first stay', () => {
    expect(accommodationGaps([makeStay()], '2024-06-03', '2024-06-08')).toEqual(['2024-06-03']);
  });

  it('is silent when there are no stays at all', () => {
    // "Every night is missing" is not useful to someone who has not booked yet.
    expect(accommodationGaps([], '2024-06-04', '2024-06-08')).toEqual([]);
  });

  it('is silent when the trip has no span', () => {
    expect(accommodationGaps([makeStay()], null, null)).toEqual([]);
  });
});

describe('stayOutsideTravel', () => {
  const flight = makeFlight({
    departure_datetime: '2024-06-04T08:00:00Z',
    arrival_datetime: '2024-06-04T12:00:00Z',
  });
  const ret = makeFlight({
    id: 'f2',
    departure_datetime: '2024-06-08T18:00:00Z',
    arrival_datetime: '2024-06-08T22:00:00Z',
  });

  it('passes a stay that overlaps the flights', () => {
    expect(stayOutsideTravel(makeStay(), [flight, ret], [])).toBeNull();
  });

  it('passes the airport hotel booked the night before departure', () => {
    // The standard case the hard validation was deliberately not written for.
    const hotel = makeStay({ check_in_date: '2024-06-03', check_out_date: '2024-06-04', nights: 1 });
    expect(stayOutsideTravel(hotel, [flight, ret], [])).toBeNull();
  });

  it('flags a stay entirely before the trip', () => {
    const wrong = makeStay({ check_in_date: '2024-05-01', check_out_date: '2024-05-04', nights: 3 });
    expect(stayOutsideTravel(wrong, [flight, ret], [])).toBe('before');
  });

  it('flags a stay entirely after the trip', () => {
    const wrong = makeStay({ check_in_date: '2024-07-01', check_out_date: '2024-07-04', nights: 3 });
    expect(stayOutsideTravel(wrong, [flight, ret], [])).toBe('after');
  });

  it('flags a check-out that runs past the last transport', () => {
    // The night after the journey home: a leg not added yet, or a mistyped date.
    const late = makeStay({ check_in_date: '2024-06-06', check_out_date: '2024-06-10', nights: 4 });
    expect(stayOutsideTravel(late, [flight, ret], [])).toBe('overruns');
  });

  it('passes a check-out on the day of the last arrival', () => {
    const same = makeStay({ check_in_date: '2024-06-04', check_out_date: '2024-06-08', nights: 4 });
    expect(stayOutsideTravel(same, [flight, ret], [])).toBeNull();
  });

  it('prefers the entirely-after message over the overrun one', () => {
    // Both are true of a stay past the last leg; the specific one wins.
    const wrong = makeStay({ check_in_date: '2024-07-01', check_out_date: '2024-07-04', nights: 3 });
    expect(stayOutsideTravel(wrong, [flight, ret], [])).toBe('after');
  });

  it('does not flag a check-in before the first departure', () => {
    // Asymmetric on purpose: the night before an early flight is a normal booking.
    const early = makeStay({ check_in_date: '2024-06-03', check_out_date: '2024-06-06', nights: 3 });
    expect(stayOutsideTravel(early, [flight, ret], [])).toBeNull();
  });

  it('says nothing when there is no transport to compare against', () => {
    expect(stayOutsideTravel(makeStay(), [], [])).toBeNull();
  });

  it('considers ground segments too', () => {
    const segment = makeSegment({
      departure_datetime: '2024-07-02T00:00:00Z',
      arrival_datetime: '2024-07-02T04:00:00Z',
    });
    const stay = makeStay({ check_in_date: '2024-07-01', check_out_date: '2024-07-02', nights: 1 });
    expect(stayOutsideTravel(stay, [], [segment])).toBeNull();

    // The overrun bound comes off the train too, not just off flights.
    const late = makeStay({ check_in_date: '2024-07-01', check_out_date: '2024-07-04', nights: 3 });
    expect(stayOutsideTravel(late, [], [segment])).toBe('overruns');
  });
});
