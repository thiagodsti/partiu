import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import EditFlightPage from './EditFlightPage.svelte';

const { mockPush, mockGet, mockUpdate } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockGet: vi.fn(),
  mockUpdate: vi.fn(),
}));

vi.mock('svelte-spa-router', async () => {
  const { readable: r } = await import('svelte/store');
  return { push: mockPush, location: r('/trips/trip-42/flights/flight-7/edit') };
});
vi.mock('../api/client', () => ({
  flightsApi: { get: mockGet, update: mockUpdate },
  airportsApi: { search: vi.fn().mockResolvedValue([]) },
}));

// i18n: return key as value so tests work without real translations
vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (key: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

const DEFAULT_PARAMS = { tripId: 'trip-42', flightId: 'flight-7' };

const FLIGHT = {
  id: 'flight-7',
  trip_id: 'trip-42',
  flight_number: 'LA800',
  airline_code: 'LA',
  airline_name: 'LATAM',
  departure_airport: 'GRU',
  arrival_airport: 'SCL',
  // 10:00 in São Paulo / 11:00 in Santiago, stored as UTC
  departure_datetime: '2025-06-01T13:00:00+00:00',
  arrival_datetime: '2025-06-01T17:00:00+00:00',
  departure_timezone: 'America/Sao_Paulo',
  arrival_timezone: 'America/Santiago',
  departure_terminal: '3',
  departure_gate: null,
  arrival_terminal: null,
  arrival_gate: null,
  seat: '12A',
  cabin_class: 'economy',
  booking_reference: 'ABC123',
  passenger_name: 'SILVA/JOAO',
  notes: 'window seat',
};

function renderPage() {
  return render(EditFlightPage, { props: { params: DEFAULT_PARAMS } });
}

describe('EditFlightPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ ...FLIGHT });
  });

  it('loads the flight and prefills the form', async () => {
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelector('input.mono[required]')).toBeInTheDocument();
    });
    const flightNumInput = container.querySelector('input.mono[required]') as HTMLInputElement;
    expect(flightNumInput.value).toBe('LA800');
    expect(mockGet).toHaveBeenCalledWith('flight-7');
  });

  it('prefills datetimes as local wall-clock time at each airport', async () => {
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelectorAll('input[type="datetime-local"]')).toHaveLength(2);
    });
    const [dep, arr] = container.querySelectorAll('input[type="datetime-local"]');
    // Stored UTC is 13:00/17:00; the form shows 10:00 GRU and 13:00 SCL.
    expect((dep as HTMLInputElement).value).toBe('2025-06-01T10:00');
    expect((arr as HTMLInputElement).value).toBe('2025-06-01T13:00');
  });

  it('sends the edited fields to flightsApi.update', async () => {
    mockUpdate.mockResolvedValue({ id: 'flight-7' });
    const { container } = renderPage();

    await waitFor(() => {
      expect(container.querySelector('input.mono[required]')).toBeInTheDocument();
    });
    const seatInput = [...container.querySelectorAll('input.mono')].find(
      (el) => (el as HTMLInputElement).value === '12A',
    ) as HTMLInputElement;
    await fireEvent.input(seatInput, { target: { value: '14C' } });

    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(
        'flight-7',
        expect.objectContaining({
          flight_number: 'LA800',
          departure_airport: 'GRU',
          arrival_airport: 'SCL',
          departure_datetime: '2025-06-01T10:00',
          seat: '14C',
        }),
      );
    });
  });

  it('navigates back to the flight detail page on success', async () => {
    mockUpdate.mockResolvedValue({ id: 'flight-7' });
    const { container } = renderPage();

    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/trips/trip-42/flights/flight-7');
    });
  });

  it('shows an error when the update fails', async () => {
    mockUpdate.mockRejectedValue(new Error('Invalid flight number format'));
    const { container, findByText } = renderPage();

    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());
    await fireEvent.submit(container.querySelector('form')!);

    expect(await findByText('Invalid flight number format')).toBeInTheDocument();
  });

  it('shows a load error instead of the form when the flight cannot be fetched', async () => {
    mockGet.mockRejectedValue(new Error('Flight not found'));
    const { container, findByText } = renderPage();

    expect(await findByText('Flight not found')).toBeInTheDocument();
    expect(container.querySelector('form')).not.toBeInTheDocument();
  });

  it('cancel link points back to the flight detail page', async () => {
    const { container } = renderPage();

    await waitFor(() => expect(container.querySelector('a.btn-secondary')).toBeInTheDocument());
    const cancelLink = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(cancelLink.getAttribute('href')).toBe('#/trips/trip-42/flights/flight-7');
  });
});
