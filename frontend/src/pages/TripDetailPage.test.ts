import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import TripDetailPage from './TripDetailPage.svelte';

const { mockGet, mockSettingsGet, mockRefreshImage, mockCheckImmichAlbum, mockDocList } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockSettingsGet: vi.fn(),
  mockRefreshImage: vi.fn(),
  mockCheckImmichAlbum: vi.fn(),
  mockDocList: vi.fn(),
}));

vi.mock('../api/client', () => ({
  tripsApi: {
    get: mockGet,
    refreshImage: mockRefreshImage,
    checkImmichAlbum: mockCheckImmichAlbum,
    createImmichAlbum: vi.fn(),
  },
  settingsApi: { get: mockSettingsGet },
  tripDocumentsApi: {
    list: mockDocList,
    upload: vi.fn(),
    viewUrl: (id: string, page = 0) => `/api/documents/${id}/view?page=${page}`,
    delete: vi.fn(),
  },
}));

vi.mock('../lib/tripImageStore', () => ({
  tripImageBust: {
    subscribe: (fn: (v: Record<string, number>) => void) => { fn({}); return () => {}; },
    bust: vi.fn(),
    urlFor: (_id: string) => '/img/test.jpg',
  },
}));

vi.mock('svelte-spa-router', () => ({
  location: { subscribe: (fn: (v: string) => void) => { fn('/trips/trip-1'); return () => {}; } },
}));

vi.mock('../lib/authStore', () => ({
  currentUser: writable({ id: '1', username: 'admin', is_admin: true }),
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string, o?: unknown) => string) => void) => {
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

// TripMap uses Leaflet which requires a real browser — stub it out
vi.mock('../components/TripMap.svelte', () => ({
  default: vi.fn(),
}));

const FLIGHT = {
  id: 'flight-1', trip_id: 'trip-1', flight_number: 'LA3001',
  airline_code: 'LA', airline_name: 'LATAM Airlines',
  departure_airport: 'GRU', arrival_airport: 'MIA',
  departure_datetime: '2025-06-01T10:00:00', arrival_datetime: '2025-06-01T18:00:00',
  departure_timezone: null, arrival_timezone: null,
  departure_terminal: null, departure_gate: null, arrival_terminal: null, arrival_gate: null,
  duration_minutes: 480, aircraft_type: null, aircraft_registration: null,
  seat: '14A', cabin_class: 'economy', booking_reference: 'ABC123',
  passenger_name: 'JOHN DOE', status: null, notes: null,
  email_subject: null, email_date: null, live_status: null,
  live_departure_delay: null, live_arrival_delay: null,
  live_departure_actual: null, live_arrival_estimated: null, live_status_fetched_at: null,
};

const TRIP = {
  id: 'trip-1', name: 'Miami Trip',
  start_date: '2025-06-01', end_date: '2025-06-10',
  origin_airport: 'GRU', destination_airport: 'MIA',
  booking_refs: ['ABC123'], flight_count: 1,
  immich_album_id: null, flights: [FLIGHT],
};

describe('TripDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSettingsGet.mockResolvedValue({ immich_url: null, immich_api_key_set: false });
    mockCheckImmichAlbum.mockResolvedValue({ exists: true });
    mockDocList.mockResolvedValue([]);
  });

  it('shows loading screen initially', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('shows error state when load fails', async () => {
    mockGet.mockRejectedValue(new Error('Trip not found'));
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.textContent).toContain('Trip not found'));
  });

  it('renders the trip name', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.textContent).toContain('Miami Trip'));
  });

  it('renders flight rows', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.textContent).toContain('GRU'));
    expect(container.textContent).toContain('MIA');
  });

  it('renders edit trip link', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() =>
      expect(container.querySelector('a[href="#/trips/trip-1/edit"]')).toBeInTheDocument(),
    );
  });

  it('renders add flight link', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() =>
      expect(container.querySelector('a[href="#/trips/trip-1/add-flight"]')).toBeInTheDocument(),
    );
  });

  it('shows empty state when trip has no flights', async () => {
    mockGet.mockResolvedValue({ ...TRIP, flights: [] });
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.textContent).toContain('trip.empty'));
  });
});
