import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import AddTransportPage from './AddTransportPage.svelte';

const { mockPush, mockCreateFlight, mockCreateSegment, mockGetTrip } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockCreateFlight: vi.fn(),
  mockCreateSegment: vi.fn(),
  mockGetTrip: vi.fn(),
}));

vi.mock('svelte-spa-router', () => ({ push: mockPush }));
vi.mock('../api/client', () => ({
  flightsApi: { create: mockCreateFlight },
  segmentsApi: { create: mockCreateSegment },
  tripsApi: { get: mockGetTrip },
  airportsApi: { search: vi.fn().mockResolvedValue([]) },
  stationsApi: { search: vi.fn().mockResolvedValue([]) },
  placesApi: { search: vi.fn().mockResolvedValue([]) },
}));

// i18n: return key as value so tests work without real translations
vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (key: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

const DEFAULT_PARAMS = { tripId: 'trip-42' };

function typeButton(container: HTMLElement, label: string): HTMLButtonElement {
  const btn = [...container.querySelectorAll('.type-option')].find((el) =>
    el.textContent?.includes(label),
  );
  if (!btn) throw new Error(`No type option matching ${label}`);
  return btn as HTMLButtonElement;
}

async function setTimes(container: HTMLElement, depart = '2025-06-01T10:00', arrive = '2025-06-01T14:00') {
  // `input`, not `change`: Svelte's `bind:value` listens on input, so a change
  // event leaves the bound state empty and the form silently invalid.
  const dateInputs = container.querySelectorAll('input[type="datetime-local"]');
  await fireEvent.input(dateInputs[0], { target: { value: depart } });
  await fireEvent.input(dateInputs[1], { target: { value: arrive } });
}

/** Fill the fields a flight needs before it can be submitted. */
async function fillFlight(container: HTMLElement, number = 'LA800', from = 'GRU', to = 'SCL') {
  const flightNumInput = container.querySelector('input.mono[required]') as HTMLInputElement;
  await fireEvent.input(flightNumInput, { target: { value: number } });
  await setTimes(container);
  const comboboxInputs = container.querySelectorAll('.airport-combobox input');
  await fireEvent.input(comboboxInputs[0], { target: { value: from } });
  await fireEvent.input(comboboxInputs[1], { target: { value: to } });
}

/** Fill the fields a ground leg needs. Places are typed by hand (no geocoder
 *  in tests), which is a supported case — it just saves without coordinates. */
async function fillGround(container: HTMLElement, from = 'Stockholm C', to = 'Oslo S') {
  const placeInputs = container.querySelectorAll('.station-input input');
  await fireEvent.input(placeInputs[0], { target: { value: from } });
  await fireEvent.input(placeInputs[1], { target: { value: to } });
  await setTimes(container);
}

describe('AddTransportPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetTrip.mockResolvedValue({ id: 'trip-42', start_date: '2026-12-30', end_date: '2027-01-02' });
  });

  // The trip's own span bounds both pickers. It is only safe to bound with
  // because `_recompute_span` unions the *declared* dates in — otherwise the
  // first leg collapses the span to its own day and the return leg would fall
  // outside its own trip.
  describe('date bounds', () => {
    const bounds = (container: HTMLElement) =>
      [...container.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]')].map((el) => [
        el.getAttribute('min'),
        el.getAttribute('max'),
      ]);

    it('bounds every date field to the trip, date-granular at both ends', async () => {
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
      await waitFor(() => expect(bounds(container)[0][0]).toBe('2026-12-30T00:00'));

      // T23:59, not the start of the day: checking in on the last day is normal,
      // and a time-carrying bound greys the whole boundary day out.
      for (const [min, max] of bounds(container)) {
        expect(min).toBe('2026-12-30T00:00');
        expect(max).toBe('2027-01-02T23:59');
      }
    });

    it('leaves the pickers unbounded when the trip has no dates', async () => {
      mockGetTrip.mockResolvedValue({ id: 'trip-42', start_date: null, end_date: null });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await waitFor(() => expect(mockGetTrip).toHaveBeenCalled());
      for (const [min, max] of bounds(container)) {
        expect(min).toBeNull();
        expect(max).toBeNull();
      }
    });

    it('suppresses a ceiling that sits before the floor', async () => {
      // min > max greys out the entire calendar, which reads as a broken picker.
      mockGetTrip.mockResolvedValue({ id: 'trip-42', start_date: '2027-01-02', end_date: '2026-12-30' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await waitFor(() => expect(bounds(container)[0][0]).toBe('2027-01-02T00:00'));
      expect(bounds(container)[0][1]).toBeNull();
    });

    it('still adds a leg when the trip lookup fails', async () => {
      mockGetTrip.mockRejectedValue(new Error('offline'));
      mockCreateFlight.mockResolvedValue({ id: 'flight-1' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fillFlight(container);
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() => expect(mockCreateFlight).toHaveBeenCalled());
    });
  });

  it('offers every transport type, with flight selected first', () => {
    const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
    const options = container.querySelectorAll('.type-option');
    expect(options).toHaveLength(5);
    expect(options[0]).toHaveClass('selected');
    expect(options[0].textContent).toContain('add_transport.type_flight');
  });

  it('cancel link points back to the trip', () => {
    const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
    const cancelLink = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(cancelLink.getAttribute('href')).toBe('#/trips/trip-42');
  });

  describe('flight', () => {
    it('shows airport comboboxes and the cabin class select', () => {
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
      expect(container.querySelectorAll('.airport-combobox')).toHaveLength(2);
      expect(container.querySelectorAll('.station-input')).toHaveLength(0);
      expect(container.querySelector('select')!.querySelectorAll('option')).toHaveLength(5);
    });

    it('creates a flight, uppercased, with the trip id', async () => {
      mockCreateFlight.mockResolvedValue({ id: 'flight-1', trip_id: 'trip-42' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fillFlight(container, 'la800', 'gru', 'scl');
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() =>
        expect(mockCreateFlight).toHaveBeenCalledWith(
          expect.objectContaining({
            trip_id: 'trip-42',
            flight_number: 'LA800',
            departure_airport: 'GRU',
            arrival_airport: 'SCL',
          }),
        ),
      );
      expect(mockCreateSegment).not.toHaveBeenCalled();
    });

    it('navigates to the trip page on success', async () => {
      mockCreateFlight.mockResolvedValue({ id: 'flight-ok', trip_id: 'trip-42' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fillFlight(container);
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/trips/trip-42'));
    });

    it('shows the error message when the API rejects', async () => {
      mockCreateFlight.mockRejectedValue(new Error('Flight already exists'));
      const { container, findByText } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fillFlight(container);
      await fireEvent.submit(container.querySelector('form')!);

      expect(await findByText('Flight already exists')).toBeInTheDocument();
    });
  });

  describe('ground leg', () => {
    it('swaps the airport comboboxes for place type-aheads', async () => {
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
      await fireEvent.click(typeButton(container, 'segments.type_train'));

      expect(container.querySelectorAll('.station-input')).toHaveLength(2);
      expect(container.querySelectorAll('.airport-combobox')).toHaveLength(0);
    });

    it('creates a segment on the trip rather than a flight', async () => {
      mockCreateSegment.mockResolvedValue({ id: 'seg-1' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fireEvent.click(typeButton(container, 'segments.type_train'));
      await fillGround(container);
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() =>
        expect(mockCreateSegment).toHaveBeenCalledWith(
          'trip-42',
          expect.objectContaining({
            type: 'train',
            departure: expect.objectContaining({ name: 'Stockholm C' }),
            arrival: expect.objectContaining({ name: 'Oslo S' }),
          }),
        ),
      );
      expect(mockCreateFlight).not.toHaveBeenCalled();
    });

    it('titles the service section with the chosen type, not "flight"', async () => {
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
      await fireEvent.click(typeButton(container, 'segments.type_ferry'));

      const titles = [...container.querySelectorAll('.form-section-title')].map((el) => el.textContent);
      expect(titles).toContain('segments.type_ferry');
      expect(titles).not.toContain('add_flight.section_route');
    });

    it('carries the chosen type through to the payload', async () => {
      mockCreateSegment.mockResolvedValue({ id: 'seg-2' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fireEvent.click(typeButton(container, 'segments.type_ferry'));
      await fillGround(container, 'Helsinki', 'Tallinn');
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() =>
        expect(mockCreateSegment).toHaveBeenCalledWith(
          'trip-42',
          expect.objectContaining({ type: 'ferry' }),
        ),
      );
    });
  });

  // Realising a leg is a train after typing its times should not cost the times.
  it('keeps the times when the type changes', async () => {
    const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
    await setTimes(container, '2025-06-01T08:30', '2025-06-01T12:45');

    await fireEvent.click(typeButton(container, 'segments.type_bus'));

    const dateInputs = container.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');
    expect(dateInputs[0].value).toBe('2025-06-01T08:30');
    expect(dateInputs[1].value).toBe('2025-06-01T12:45');
  });

  // Every field is on the page; the asterisks are what separate what the form
  // needs from what it merely accepts.
  it('shows all fields with no disclosure, marking only the required ones', async () => {
    const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
    expect(container.querySelector('details')).toBeNull();

    // Flight: number, both airports, both times.
    expect(container.querySelectorAll('.form-label .req')).toHaveLength(5);
    // Optional fields are present and unmarked — terminal, gate, cabin, notes.
    expect(container.querySelector('textarea')).toBeInTheDocument();
    expect(container.querySelector('select')).toBeInTheDocument();
  });

  it('marks only the four fields a ground leg requires', async () => {
    const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
    await fireEvent.click(typeButton(container, 'segments.type_train'));
    expect(container.querySelectorAll('.form-label .req')).toHaveLength(4);
  });

  // You are the one driving a car — there is no seat to be assigned.
  describe('car', () => {
    const labels = (container: HTMLElement) =>
      [...container.querySelectorAll('.form-label')].map((el) => el.textContent?.trim());

    it('drops the seat field', async () => {
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
      expect(labels(container).some((l) => l?.startsWith('add_flight.seat'))).toBe(true);

      await fireEvent.click(typeButton(container, 'segments.type_car'));
      expect(labels(container).some((l) => l?.startsWith('add_flight.seat'))).toBe(false);
      // The booking reference still makes sense for a rental.
      expect(labels(container).some((l) => l?.startsWith('add_flight.booking_ref'))).toBe(true);
    });

    it('does not carry a seat typed before the switch into the payload', async () => {
      mockCreateSegment.mockResolvedValue({ id: 'seg-3' });
      const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });

      await fireEvent.click(typeButton(container, 'segments.type_train'));
      const seatInput = [...container.querySelectorAll('.form-field')].find((f) =>
        f.querySelector('.form-label')?.textContent?.startsWith('add_flight.seat'),
      )!.querySelector('input')!;
      await fireEvent.input(seatInput, { target: { value: 'Vagão 3, 12A' } });

      await fireEvent.click(typeButton(container, 'segments.type_car'));
      await fillGround(container, 'Faro', 'Lagos');
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() =>
        expect(mockCreateSegment).toHaveBeenCalledWith(
          'trip-42',
          expect.objectContaining({ type: 'car', seat: null }),
        ),
      );
    });
  });

  it('will not submit until the required fields are filled', async () => {
    const { container } = render(AddTransportPage, { props: { params: DEFAULT_PARAMS } });
    const submitBtn = container.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);

    await fillFlight(container);
    expect(submitBtn.disabled).toBe(false);
  });
});
