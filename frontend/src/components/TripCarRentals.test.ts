import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import TripCarRentals from './TripCarRentals.svelte';
import type { Trip, TripCarRental } from '../api/types';

const { mockList, mockCreate, mockUpdate, mockDelete } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('../api/client', () => ({
  carRentalsApi: {
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
  name: 'Vienna',
  start_date: '2026-03-29',
  end_date: '2026-04-01',
  origin_airport: null,
  destination_airport: null,
  booking_refs: [],
};

const RENTAL: TripCarRental = {
  id: 'r1',
  trip_id: 't1',
  vendor: 'Hertz',
  pickup: {
    name: 'Vienna Airport',
    address: null,
    lat: null,
    lon: null,
    timezone: null,
    country_code: 'AT',
  },
  pickup_datetime: '2026-03-29T09:30:00Z',
  pickup_date: '2026-03-29',
  dropoff: {
    name: 'Vienna Airport',
    address: null,
    lat: null,
    lon: null,
    timezone: null,
    country_code: 'AT',
  },
  dropoff_datetime: '2026-04-01T23:00:00Z',
  dropoff_date: '2026-04-01',
  days: 3,
  is_one_way: false,
  booking_reference: 'X11223344Y',
  vehicle: 'Fiat 500 or similar',
  driver_name: null,
  notes: null,
  created_by: 1,
  created_by_username: 'me',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const dateInputs = (container: HTMLElement) =>
  container.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');

const textInputs = (container: HTMLElement) =>
  container.querySelectorAll<HTMLInputElement>('input[type="text"]');

describe('TripCarRentals', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue({ id: 'new', ok: true });
    mockUpdate.mockResolvedValue({ ok: true });
    mockDelete.mockResolvedValue(null);
  });

  async function openAddForm() {
    const rendered = render(TripCarRentals, { trip: TRIP });
    await waitFor(() => rendered.getByText('+ car_rentals.add'));
    await fireEvent.click(rendered.getByText('+ car_rentals.add'));
    return rendered;
  }

  it('shows the empty state when the trip has no rental', async () => {
    const { getByText } = render(TripCarRentals, { trip: TRIP });
    await waitFor(() => getByText('car_rentals.empty'));
  });

  it('reports the loaded list upward so the header and planner see it', async () => {
    // The onchange contract TripStays has: the trip page feeds the day planner
    // from this rather than fetching the list a second time.
    mockList.mockResolvedValue([RENTAL]);
    const onchange = vi.fn();
    render(TripCarRentals, { trip: TRIP, onchange });
    await waitFor(() => expect(onchange).toHaveBeenCalledWith([RENTAL]));
  });

  it('hides the drop-off counter for a return hire', async () => {
    // Defaulting to "same counter" halves the form for the common hire; the
    // second picker only appears when it is actually a different place.
    const { container, getByText } = await openAddForm();
    expect(container.textContent).not.toContain('car_rentals.dropoff_place');

    await fireEvent.click(getByText('car_rentals.same_return'));
    expect(container.textContent).toContain('car_rentals.dropoff_place');
  });

  it('sends the pick-up counter as both ends of a return hire', async () => {
    const { container, getByText } = await openAddForm();
    await fireEvent.input(textInputs(container)[0], { target: { value: 'Hertz' } });
    // The PlaceInput's own box is found by its placeholder rather than by
    // position, so adding a field above it does not silently retarget this.
    const pickup = Array.from(textInputs(container)).find((i) =>
      i.placeholder.includes('pickup_place'),
    );
    await fireEvent.input(pickup!, { target: { value: 'Vienna Airport' } });

    await fireEvent.click(getByText('car_rentals.save'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const [, payload] = mockCreate.mock.calls[0];
    expect(payload.pickup.name).toBe('Vienna Airport');
    expect(payload.dropoff.name).toBe('Vienna Airport');
  });

  it('greys out every day before the pick-up day', async () => {
    // Date-granular, not the pick-up instant: a min carrying 09:00 makes that
    // day's earlier hours invalid and browsers grey the whole day out, so the
    // day you actually collect the car reads as disabled.
    const { container } = await openAddForm();
    expect(dateInputs(container)[1].getAttribute('min')).toBe('2026-03-29T00:00');
  });

  it('moves the floor when the pick-up changes', async () => {
    const { container } = await openAddForm();
    await fireEvent.input(dateInputs(container)[0], { target: { value: '2026-06-01T18:00' } });
    expect(dateInputs(container)[1].getAttribute('min')).toBe('2026-06-01T00:00');
  });

  it('sets no floor while the pick-up is empty', async () => {
    const noDates: Trip = { ...TRIP, start_date: null, end_date: null };
    const rendered = render(TripCarRentals, { trip: noDates });
    await waitFor(() => rendered.getByText('+ car_rentals.add'));
    await fireEvent.click(rendered.getByText('+ car_rentals.add'));

    // An empty string would be an unparseable min. Absent is clearer.
    expect(dateInputs(rendered.container)[1].hasAttribute('min')).toBe(false);
  });

  it('says what is wrong when the drop-off is before the pick-up', async () => {
    // Its own message rather than a silently disabled Save: a button disabled
    // for unstated reasons is a dead end.
    const { container, getByText } = await openAddForm();
    await fireEvent.input(dateInputs(container)[1], { target: { value: '2026-03-28T09:00' } });
    getByText('car_rentals.error_dropoff_order');
  });

  it('opens the editor with the stored rental', async () => {
    mockList.mockResolvedValue([RENTAL]);
    const { getByText, container } = render(TripCarRentals, { trip: TRIP });
    await waitFor(() => getByText('Hertz'));

    await fireEvent.click(getByText('Hertz'));

    const vendor = textInputs(container)[0];
    expect(vendor.value).toBe('Hertz');
    expect(getByText('car_rentals.delete')).toBeTruthy();
  });
});
