import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import EditTripPage from './EditTripPage.svelte';

const { mockPush, mockGet, mockUpdate, mockSegments, mockStays, mockAirportGet } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockGet: vi.fn(),
  mockUpdate: vi.fn(),
  mockSegments: vi.fn(),
  mockStays: vi.fn(),
  mockAirportGet: vi.fn(),
}));

vi.mock('svelte-spa-router', () => ({ push: mockPush }));
vi.mock('../api/client', () => ({
  tripsApi: {
    get: mockGet,
    update: mockUpdate,
  },
  citiesApi: { search: vi.fn().mockResolvedValue([]) },
  airportsApi: { get: mockAirportGet, search: vi.fn().mockResolvedValue([]) },
  segmentsApi: { list: mockSegments },
  staysApi: { list: mockStays },
  stationsApi: { search: vi.fn().mockResolvedValue([]) },
  placesApi: { search: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const TRIP = {
  id: 'trip-99',
  name: 'Tokyo 2025',
  start_date: '2025-03-01',
  end_date: '2025-03-14',
  origin_airport: 'GRU',
  destination_airport: 'NRT',
  booking_refs: ['TK123'],
  origin_place: 'Florianópolis',
  origin_lat: -27.5954,
  origin_lon: -48.548,
  origin_country: 'BR',
  destinations: [
    { name: 'São Paulo', lat: -23.5505, lon: -46.6333, country_code: 'BR' },
    { name: 'Rio de Janeiro', lat: -22.9068, lon: -43.1729, country_code: 'BR' },
  ],
};

describe('EditTripPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue(TRIP);
    mockUpdate.mockResolvedValue({});
    mockSegments.mockResolvedValue([]);
    mockStays.mockResolvedValue([]);
    mockAirportGet.mockResolvedValue({
      iata_code: 'GRU', city_name: 'São Paulo', country_code: 'BR',
      latitude: -23.43, longitude: -46.47,
    });
  });

  it('shows loading state before trip loads', () => {
    mockGet.mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(EditTripPage, {
      props: { params: { id: 'trip-99' } },
    });
    expect(container.querySelector('.loading-placeholder')).toBeInTheDocument();
  });

  it('renders form with trip data after loading', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });

    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const nameInput = container.querySelector('input[type="text"][required]') as HTMLInputElement;
    expect(nameInput.value).toBe('Tokyo 2025');
  });

  it('shows load error when tripsApi.get fails', async () => {
    mockGet.mockRejectedValue(new Error('Not found'));
    const { findByText } = render(EditTripPage, { props: { params: { id: 'bad-id' } } });
    expect(await findByText('Not found')).toBeInTheDocument();
  });

  it('renders two date inputs pre-filled', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const dateInputs = container.querySelectorAll('input[type="date"]');
    expect(dateInputs).toHaveLength(2);
    expect((dateInputs[0] as HTMLInputElement).value).toBe('2025-03-01');
    expect((dateInputs[1] as HTMLInputElement).value).toBe('2025-03-14');
  });

  it('leaves the trip-level booking references alone', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][1]).not.toHaveProperty('booking_refs');
  });

  it('cancel link points back to the trip', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('a.btn-secondary')).toBeInTheDocument());

    const link = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('#/trips/trip-99');
  });

  it('calls tripsApi.update with edited name on submit', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const nameInput = container.querySelector('input[type="text"][required]')!;
    await fireEvent.input(nameInput, { target: { value: 'Tokyo 2025 Updated' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(
        'trip-99',
        expect.objectContaining({ name: 'Tokyo 2025 Updated' }),
      );
    });
  });

  it('navigates back to trip detail on success', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/trips/trip-99'));
  });

  it('shows error message when update fails', async () => {
    mockUpdate.mockRejectedValue(new Error('Save failed'));
    const { container, findByText } = render(EditTripPage, {
      props: { params: { id: 'trip-99' } },
    });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);
    expect(await findByText('Save failed')).toBeInTheDocument();
  });

  // The cover photo comes from the destinations now, so the airport field that
  // used to pick it is gone — there is nothing left for an IATA code to do here.
  it('offers no airport fields at all', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    expect(container.querySelectorAll('.airport-combobox')).toHaveLength(0);
  });

  it('pre-fills the typed ends and sends them back as places', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const places = container.querySelectorAll<HTMLInputElement>('.station-input input');
    expect(places).toHaveLength(3);
    expect(places[0].value).toBe('Florianópolis');
    expect(places[1].value).toBe('São Paulo');
    expect(places[2].value).toBe('Rio de Janeiro');

    await fireEvent.submit(container.querySelector('form')!);
    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][1]).toMatchObject({
      origin: expect.objectContaining({ name: 'Florianópolis' }),
      destinations: [
        expect.objectContaining({ name: 'São Paulo', country_code: 'BR' }),
        expect.objectContaining({ name: 'Rio de Janeiro' }),
      ],
    });
  });

  // Shortening a trip past one of its own legs is not an error — the span is
  // the declared dates unioned with the contents, so that end simply will not
  // move. Saying which leg holds it beats a save that appears to do nothing.
  describe('shortening the trip past a leg', () => {
    const CAR_LEG = {
      id: 'seg-1',
      type: 'car',
      departure: { name: 'São Paulo', timezone: 'America/Sao_Paulo' },
      arrival: { name: 'Florianópolis', timezone: 'America/Sao_Paulo' },
      // Inside the fixture trip (1–14 March), and stored as UTC: 12:00Z on the
      // 14th is 09:00 on the 14th in São Paulo. (01:00Z would have been 22:00 on
      // the *13th* there — which is why the dates are compared locally.)
      departure_datetime: '2025-03-13T11:00:00Z',
      arrival_datetime: '2025-03-14T12:00:00Z',
    };

    it('warns, naming the dates the legs hold', async () => {
      mockSegments.mockResolvedValue([CAR_LEG]);
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
      await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());
      await waitFor(() => expect(mockSegments).toHaveBeenCalled());

      const dates = container.querySelectorAll<HTMLInputElement>('input[type="date"]');
      await fireEvent.input(dates[1], { target: { value: '2025-03-13' } });

      await waitFor(() =>
        expect(container.querySelector('.form-warning')).toBeInTheDocument(),
      );
    });

    it('does not warn while the dates still cover every leg', async () => {
      mockSegments.mockResolvedValue([CAR_LEG]);
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
      await waitFor(() => expect(mockSegments).toHaveBeenCalled());

      expect(container.querySelector('.form-warning')).toBeNull();
    });

    it('never blocks the save', async () => {
      mockSegments.mockResolvedValue([CAR_LEG]);
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
      await waitFor(() => expect(mockSegments).toHaveBeenCalled());

      const dates = container.querySelectorAll<HTMLInputElement>('input[type="date"]');
      await fireEvent.input(dates[1], { target: { value: '2025-03-13' } });
      await fireEvent.submit(container.querySelector('form')!);

      await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    });

    it('says nothing when the leg lookup fails', async () => {
      mockSegments.mockRejectedValue(new Error('offline'));
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
      await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

      expect(container.querySelector('.form-warning')).toBeNull();
    });
  });

  // Typing in a destination row must not throw: an exception here trips the
  // app's error boundary, which replaces the whole page with "This page didn't
  // load." rather than showing a field that failed.
  it('accepts typing in a new destination row', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.click(container.querySelector('.destination-add')!);
    const rows = container.querySelectorAll('.destination-row .station-input input');
    await fireEvent.input(rows[rows.length - 1], { target: { value: 'Belém' } });

    expect((rows[rows.length - 1] as HTMLInputElement).value).toBe('Belém');
  });

  /* A trip built from email has airports but no typed cities, so this form used
   * to open blank on exactly the trips that already knew where they went. The
   * cities are seeded into the form — offered, not written behind your back. */
  describe('seeding from the trip’s flights', () => {
    const noPlaces = { ...TRIP, origin_place: null, destinations: [] };

    it('fills the cities in from the airports', async () => {
      mockGet.mockResolvedValue(noPlaces);
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });

      await waitFor(() =>
        expect(
          (container.querySelectorAll('.station-input input')[0] as HTMLInputElement).value,
        ).toBe('São Paulo'),
      );
      // The airport's coordinates and country ride along, so the seeded place is
      // complete rather than a bare label.
      await fireEvent.submit(container.querySelector('form')!);
      await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
      expect(mockUpdate.mock.calls[0][1].origin).toMatchObject({
        name: 'São Paulo',
        country_code: 'BR',
        lat: -23.43,
      });
    });

    it('says where the values came from', async () => {
      mockGet.mockResolvedValue(noPlaces);
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });

      await waitFor(() => expect(container.textContent).toContain('trips.route_seeded'));
    });

    it('never overwrites what the traveller already typed', async () => {
      mockGet.mockResolvedValue(TRIP); // already has Florianópolis / São Paulo, Rio
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
      await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

      expect(
        (container.querySelectorAll('.station-input input')[0] as HTMLInputElement).value,
      ).toBe('Florianópolis');
      expect(mockAirportGet).not.toHaveBeenCalled();
      expect(container.textContent).not.toContain('trips.route_seeded');
    });

    it('leaves the field empty when the airport is unknown', async () => {
      mockGet.mockResolvedValue(noPlaces);
      mockAirportGet.mockRejectedValue(new Error('404'));
      const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
      await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

      // An IATA code in a field that asks for a city would be worse than blank.
      expect(
        (container.querySelectorAll('.station-input input')[0] as HTMLInputElement).value,
      ).toBe('');
    });
  });

  it('leaves the derived origin alone when saving', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][1]).not.toHaveProperty('origin_airport');
  });
});
