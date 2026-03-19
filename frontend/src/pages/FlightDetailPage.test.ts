import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import FlightDetailPage from './FlightDetailPage.svelte';

const { mockGet, mockAircraft, mockAirportGet } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAircraft: vi.fn(),
  mockAirportGet: vi.fn(),
}));

vi.mock('../api/client', () => ({
  flightsApi: { get: mockGet, aircraft: mockAircraft, email: vi.fn() },
  airportsApi: { get: mockAirportGet },
}));

vi.mock('svelte-spa-router', () => ({
  location: { subscribe: (fn: (v: string) => void) => { fn('/trips/trip-1/flights/flight-1'); return () => {}; } },
}));

vi.mock('../lib/authStore', () => ({
  currentUser: writable({ id: '1', username: 'admin', is_admin: true }),
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

vi.mock('svelte-i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const FLIGHT = {
  id: 'flight-1',
  trip_id: 'trip-1',
  flight_number: 'LA3001',
  airline_code: 'LA',
  airline_name: 'LATAM Airlines',
  departure_airport: 'GRU',
  arrival_airport: 'MIA',
  departure_datetime: '2025-06-01T10:00:00',
  arrival_datetime: '2025-06-01T18:00:00',
  departure_timezone: 'America/Sao_Paulo',
  arrival_timezone: 'America/New_York',
  departure_terminal: null, departure_gate: null,
  arrival_terminal: null, arrival_gate: null,
  duration_minutes: 480,
  aircraft_type: 'Boeing 737',
  aircraft_registration: null,
  seat: '14A', cabin_class: 'economy',
  booking_reference: 'ABC123',
  passenger_name: 'JOHN DOE',
  status: null, notes: null, email_subject: null, email_date: null,
  live_status: null, live_departure_delay: null, live_arrival_delay: null,
  live_departure_actual: null, live_arrival_estimated: null, live_status_fetched_at: null,
};

describe('FlightDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAirportGet.mockResolvedValue({ iata_code: 'GRU', name: 'Guarulhos', city_name: 'São Paulo', country_code: 'BR', latitude: -23.43, longitude: -46.47 });
    mockAircraft.mockResolvedValue(null);
  });

  it('shows loading screen initially', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('shows error state when load fails', async () => {
    mockGet.mockRejectedValue(new Error('Not found'));
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.textContent).toContain('Not found'));
  });

  it('renders departure and arrival airports', async () => {
    mockGet.mockResolvedValue(FLIGHT);
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.textContent).toContain('GRU'));
    expect(container.textContent).toContain('MIA');
  });

  it('renders flight number', async () => {
    mockGet.mockResolvedValue(FLIGHT);
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.textContent).toContain('LA3001'));
  });

  it('renders passenger name', async () => {
    mockGet.mockResolvedValue(FLIGHT);
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.textContent).toContain('JOHN DOE'));
  });

  it('renders booking reference', async () => {
    mockGet.mockResolvedValue(FLIGHT);
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.textContent).toContain('ABC123'));
  });

  it('renders aircraft type when available', async () => {
    mockGet.mockResolvedValue(FLIGHT);
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.textContent).toContain('Boeing 737'));
  });

  it('renders a back link', async () => {
    mockGet.mockResolvedValue(FLIGHT);
    const { container } = render(FlightDetailPage, { props: { params: { tripId: 'trip-1', flightId: 'flight-1' } } });
    await waitFor(() => expect(container.querySelector('a[href*="trip-1"]')).toBeInTheDocument());
  });
});
