import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import TripStays from './TripStays.svelte';
import type { Flight, Trip, TripStay } from '../api/types';

const { mockList, mockCreate, mockUpdate, mockDelete } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('../api/client', () => ({
  staysApi: {
    list: mockList,
    create: mockCreate,
    update: mockUpdate,
    delete: mockDelete,
  },
  stationsApi: { search: vi.fn() },
  placesApi: { search: vi.fn() },
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string, o?: { values?: Record<string, unknown> }) => string) => void) => {
      fn((k: string, o?: { values?: Record<string, unknown> }) =>
        o?.values ? `${k} ${JSON.stringify(o.values)}` : k,
      );
      return () => {};
    },
  },
}));

const TRIP: Trip = {
  id: 't1',
  name: 'Lisbon',
  start_date: '2026-05-10',
  end_date: '2026-05-14',
  origin_airport: null,
  destination_airport: null,
  booking_refs: [],
};

const STAY: TripStay = {
  id: 's1',
  trip_id: 't1',
  kind: 'hotel',
  place: {
    name: 'Hotel Lisboa',
    address: null,
    lat: null,
    lon: null,
    timezone: null,
    country_code: 'PT',
  },
  check_in_datetime: '2026-05-10T14:00:00Z',
  check_out_datetime: '2026-05-13T09:00:00Z',
  check_in_date: '2026-05-10',
  check_out_date: '2026-05-13',
  booking_reference: null,
  confirmation: null,
  contact: null,
  room_type: null,
  guests: null,
  notes: null,
  nights: 3,
  created_by: 1,
  created_by_username: 'me',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

// Lands home on the 12th, a day before STAY checks out on the 13th.
const EARLY_RETURN = {
  id: 'f1',
  trip_id: 't1',
  flight_number: 'TP1234',
  departure_airport: 'LIS',
  arrival_airport: 'ARN',
  departure_datetime: '2026-05-12T08:00:00Z',
  arrival_datetime: '2026-05-12T13:00:00Z',
  duration_minutes: 300,
  airline_code: 'TP',
  status: 'past',
} as Flight;

function props() {
  return { trip: TRIP, flights: [], segments: [] };
}

describe('TripStays check-out against the travel window', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue({ id: 'new', ok: true });
    mockUpdate.mockResolvedValue({ ok: true });
  });

  async function openAddForm(flights: Flight[] = []) {
    const rendered = render(TripStays, { ...props(), flights });
    await waitFor(() => rendered.getByText('+ stays.add'));
    await fireEvent.click(rendered.getByText('+ stays.add'));
    // A name is required for the form to validate at all; typing into the
    // PlaceInput reports a hand-typed place back with no coordinates.
    const name = rendered.container.querySelector('input[type="text"]') as HTMLInputElement;
    await fireEvent.input(name, { target: { value: 'Hotel Lisboa' } });
    return rendered;
  }

  const dateInputs = (container: HTMLElement) =>
    container.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');

  it('greys out every day before the check-in day', async () => {
    const { container } = await openAddForm();
    // openAdd seeds check-in to the trip's first day at 14:00; the floor is
    // that day at midnight, so the check-in day itself stays selectable.
    expect(dateInputs(container)[1].getAttribute('min')).toBe('2026-05-10T00:00');
  });

  it('moves the floor when check-in changes', async () => {
    const { container } = await openAddForm();

    await fireEvent.input(dateInputs(container)[0], { target: { value: '2026-06-01T18:00' } });

    expect(dateInputs(container)[1].getAttribute('min')).toBe('2026-06-01T00:00');
  });

  it('sets no floor while check-in is empty', async () => {
    const noDates: Trip = { ...TRIP, start_date: null, end_date: null };
    const rendered = render(TripStays, { ...props(), trip: noDates });
    await waitFor(() => rendered.getByText('+ stays.add'));
    await fireEvent.click(rendered.getByText('+ stays.add'));

    // An empty string would be an unparseable min. Absent is clearer.
    expect(dateInputs(rendered.container)[1].hasAttribute('min')).toBe(false);
  });

  it('greys out every day after the last transport', async () => {
    const { container } = await openAddForm([EARLY_RETURN]);
    // End of that day, so checking out on the morning you fly home still works.
    expect(dateInputs(container)[1].getAttribute('max')).toBe('2026-05-12T23:59');
  });

  it('sets no ceiling when the trip has no transport', async () => {
    const { container } = await openAddForm();
    expect(dateInputs(container)[1].hasAttribute('max')).toBe(false);
  });

  it('drops the ceiling rather than inverting the range', async () => {
    // One-way flight out, return not added yet, check-in after it: min > max
    // would grey out the whole calendar. The message covers this instead.
    const { container } = await openAddForm([EARLY_RETURN]);

    await fireEvent.input(dateInputs(container)[0], { target: { value: '2026-05-20T14:00' } });

    expect(dateInputs(container)[1].hasAttribute('max')).toBe(false);
    expect(dateInputs(container)[1].getAttribute('min')).toBe('2026-05-20T00:00');
  });

  it('seeds the standard hotel day at both ends', async () => {
    const { container } = await openAddForm();

    expect(dateInputs(container)[0].value).toBe('2026-05-10T14:00');
    // No transport on this trip, so check-out falls back to the trip's end.
    expect(dateInputs(container)[1].value).toBe('2026-05-14T11:00');
  });

  it('seeds check-out from the last transport, not the trip end', async () => {
    // trip.end_date counts other stays; seeding from it could open the form
    // already showing the after-travel error.
    const { container } = await openAddForm([EARLY_RETURN]);

    expect(dateInputs(container)[1].value).toBe('2026-05-12T11:00');
    expect(container.textContent).not.toContain('stays.error_after_travel');
  });

  it('leaves both ends empty on a trip with no dates at all', async () => {
    const noDates: Trip = { ...TRIP, start_date: null, end_date: null };
    const rendered = render(TripStays, { ...props(), trip: noDates });
    await waitFor(() => rendered.getByText('+ stays.add'));
    await fireEvent.click(rendered.getByText('+ stays.add'));

    expect(dateInputs(rendered.container)[0].value).toBe('');
    expect(dateInputs(rendered.container)[1].value).toBe('');
  });

  it('sends the local datetime straight through', async () => {
    const { container, getByText } = await openAddForm();

    await fireEvent.input(dateInputs(container)[1], { target: { value: '2026-05-12T09:30' } });
    await fireEvent.click(getByText('stays.save'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const [, payload] = mockCreate.mock.calls[0];
    expect(payload.check_in_datetime).toBe('2026-05-10T14:00');
    expect(payload.check_out_datetime).toBe('2026-05-12T09:30');
  });

  it('blocks a check-out after the last transport, and says why', async () => {
    const { container, getByText } = await openAddForm([EARLY_RETURN]);

    await fireEvent.input(dateInputs(container)[1], { target: { value: '2026-05-13T10:00' } });

    expect(container.textContent).toContain('stays.error_after_travel');
    expect((getByText('stays.save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('allows a check-out on the day of the last transport', async () => {
    const { container, getByText } = await openAddForm([EARLY_RETURN]);

    // Checking out the morning of an afternoon flight home.
    await fireEvent.input(dateInputs(container)[1], { target: { value: '2026-05-12T10:00' } });

    expect(container.textContent).not.toContain('stays.error_after_travel');
    expect((getByText('stays.save') as HTMLButtonElement).disabled).toBe(false);
  });

  it('bounds nothing when the trip has no transport yet', async () => {
    // Accommodation is often booked before any leg is. Nothing to measure against.
    const { container, getByText } = await openAddForm([]);

    await fireEvent.input(dateInputs(container)[1], { target: { value: '2027-01-01T10:00' } });

    expect(container.textContent).not.toContain('stays.error_after_travel');
    expect((getByText('stays.save') as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps save disabled for a check-out equal to check-in, and says why', async () => {
    const { container, getByText } = await openAddForm();

    await fireEvent.input(dateInputs(container)[1], { target: { value: '2026-05-10T14:00' } });

    expect(container.textContent).toContain('stays.error_check_out_order');
    expect((getByText('stays.save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('says nothing about ordering before check-out has been filled in', async () => {
    const { container } = await openAddForm();
    expect(container.textContent).not.toContain('stays.error_check_out_order');
  });

  it('refuses to save a stay that would outrun the transport', async () => {
    const { container, getByText } = await openAddForm([EARLY_RETURN]);

    await fireEvent.input(dateInputs(container)[1], { target: { value: '2026-05-13T10:00' } });
    await fireEvent.click(getByText('stays.save'));

    expect(mockCreate).not.toHaveBeenCalled();
  });
});

describe('TripStays out-of-travel warning', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([STAY]);
  });

  it('warns when the check-out runs past the last transport', async () => {
    const { container, getByText } = render(TripStays, { ...props(), flights: [EARLY_RETURN] });
    await waitFor(() => getByText('Hotel Lisboa'));

    expect(container.textContent).toContain('stays.warn_overruns');
  });

  it('stays quiet when the transport outlasts the stay', async () => {
    const late = { ...EARLY_RETURN, arrival_datetime: '2026-05-14T13:00:00Z' };
    const { container, getByText } = render(TripStays, { ...props(), flights: [late] });
    await waitFor(() => getByText('Hotel Lisboa'));

    expect(container.textContent).not.toContain('stays.warn');
  });
});
