import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import TripDetailPage from './TripDetailPage.svelte';

const { mockGet, mockSettingsGet, mockRefreshImage, mockCheckImmichAlbum, mockDocList, mockBpListForTrip, mockBudgetGet } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockSettingsGet: vi.fn(),
  mockRefreshImage: vi.fn(),
  mockCheckImmichAlbum: vi.fn(),
  mockDocList: vi.fn(),
  mockBpListForTrip: vi.fn(),
  mockBudgetGet: vi.fn(),
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
  boardingPassesApi: {
    listForTrip: mockBpListForTrip,
    imageUrl: (id: string) => `/api/boarding-passes/${id}/image`,
    delete: vi.fn(),
  },
  budgetApi: { get: mockBudgetGet, set: vi.fn(), clear: vi.fn() },
  expensesApi: {
    list: vi.fn().mockResolvedValue([]),
    participants: vi.fn().mockResolvedValue([]),
    balances: vi.fn().mockResolvedValue({ balances: {} }),
  },
  guestsApi: { list: vi.fn().mockResolvedValue([]) },
  segmentsApi: { list: vi.fn().mockResolvedValue([]) },
  staysApi: { list: vi.fn().mockResolvedValue([]) },
  sharesApi: {
    listTripShares: vi.fn().mockResolvedValue([]),
    shareTrip: vi.fn(),
    revokeTripShare: vi.fn(),
    leaveTrip: vi.fn(),
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
    mockBpListForTrip.mockResolvedValue([]);
    mockBudgetGet.mockResolvedValue({ amount: null, currency: null, spent: 0, uncounted: {} });
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

  // One entry point for flights and ground legs alike — the old page had two
  // buttons, and the split was never how anyone thinks about a trip.
  it('renders add transport link', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() =>
      expect(container.querySelector('a[href="#/trips/trip-1/add-transport"]')).toBeInTheDocument(),
    );
    expect(container.querySelector('a[href="#/trips/trip-1/add-flight"]')).toBeNull();
  });

  // The button lived on the trip page all along but was revealed by a selector
  // naming only the card's cover class, so on a pointer device it sat at
  // opacity 0 forever — present, positioned, and invisible.
  it('offers the image refresh inside the trip, labelled', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() =>
      expect(container.querySelector('.trip-detail-cover .trip-card-img-refresh')).toBeInTheDocument(),
    );
    const btn = container.querySelector('.trip-card-img-refresh') as HTMLButtonElement;
    // Localised, not the hardcoded English string it used to carry.
    expect(btn.getAttribute('title')).toBe('trips.refresh_image');
    expect(btn.getAttribute('aria-label')).toBe('trips.refresh_image');
  });

  it('asks the API for a different image when it is clicked', async () => {
    mockGet.mockResolvedValue(TRIP);
    mockRefreshImage.mockResolvedValue({ ok: true });
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() =>
      expect(container.querySelector('.trip-card-img-refresh')).toBeInTheDocument(),
    );
    await fireEvent.click(container.querySelector('.trip-card-img-refresh')!);

    await waitFor(() => expect(mockRefreshImage).toHaveBeenCalledWith('trip-1'));
  });

  // The header answers "what is on this trip" without scrolling: every kind it
  // holds, named. The card can only manage a coarser version.
  it('summarises what the trip holds under its dates', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() =>
      expect(container.querySelector('.trip-header-contents')).toBeInTheDocument(),
    );
    // One flight on the fixture trip, and no ground legs or stays to name.
    expect(container.querySelector('.trip-header-contents')?.textContent).toContain('✈');
  });

  it('shows the expense total alongside what the trip holds', async () => {
    mockGet.mockResolvedValue({ ...TRIP, expenses_total: { EUR: 420, SEK: 900 } });
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() =>
      expect(container.querySelector('.trip-header-contents')?.textContent).toContain('EUR 420'),
    );
    expect(container.querySelector('.trip-header-contents')?.textContent).toContain('SEK 900');
  });

  /* Its own chip, not folded into the expense totals beside it: those are the
   * *trip's* spend per currency, this is your share against your limit. Adding
   * the two together would be a lie. */
  it('shows the budget in the header summary, with its state', async () => {
    mockGet.mockResolvedValue(TRIP);
    mockBudgetGet.mockResolvedValue({
      amount: 800,
      currency: 'EUR',
      spent: 700,
      uncounted: {},
    });
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() =>
      expect(container.querySelector('.trip-header-budget')).toBeInTheDocument(),
    );
    const chip = container.querySelector('.trip-header-budget')!;
    expect(chip.textContent).toContain('EUR 700');
    expect(chip.textContent).toContain('EUR 800');
    expect(chip.getAttribute('data-level')).toBe('near');
  });

  it('leaves the header alone when no budget is set', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() =>
      expect(container.querySelector('.trip-header-contents')).toBeInTheDocument(),
    );
    expect(container.querySelector('.trip-header-budget')).toBeNull();
  });

  it('says nothing at all when the trip is empty', async () => {
    mockGet.mockResolvedValue({ ...TRIP, flights: [] });
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() => expect(container.textContent).toContain('trip.empty'));
    expect(container.querySelector('.trip-header-contents')).toBeNull();
  });

  // Adding a leg belongs beside the list it adds to. The header carried a second
  // copy of the same button, which is one door too many to the same room.
  it('keeps the add button out of the trip header', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.querySelector('.trip-actions')).toBeInTheDocument());
    expect(container.querySelector('.trip-actions a[href*="add-transport"]')).toBeNull();
  });

  it('shows empty state when trip has no flights', async () => {
    mockGet.mockResolvedValue({ ...TRIP, flights: [] });
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.textContent).toContain('trip.empty'));
  });

  // The desktop layout is spine + sidebar rather than one balanced grid, so the
  // two columns flow independently and a short card cannot open a row-band hole
  // beneath itself. That only holds while each section sits in the right wrapper.
  it('puts the itinerary in the spine and the ancillary cards in the aside', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.querySelector('.trip-spine')).toBeInTheDocument());

    const titlesIn = (sel: string) =>
      [...container.querySelectorAll(`${sel} .trip-section-title`)].map((el) => el.textContent);

    // Documents rides at the foot of the spine: it is the least-used card on the
    // page, and keeping it out of the aside stops that column becoming a stack
    // of three things nobody opens.
    expect(titlesIn('.trip-spine')).toEqual([
      'trip.transport',
      'stays.title',
      'planner.title',
      'trip.documents',
    ]);
    expect(titlesIn('.trip-aside')).toEqual([
      'packing.title',
      'expenses.title',
      'trips.note_label',
      'trips.rating_label',
    ]);
  });

  it('compacts the documents section when there is nothing in it', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() => expect(container.querySelector('.trip-aside')).toBeInTheDocument());

    const docs = [...container.querySelectorAll('.trip-section')].find(
      (el) => el.querySelector('.trip-section-title')?.textContent === 'trip.documents',
    );
    expect(docs).toHaveClass('trip-section-compact');
    // The empty line moved onto the header row instead of being a body of its own.
    expect(docs?.querySelector('.trip-section-header .section-note')?.textContent).toBe(
      'trip.doc_empty',
    );
    expect(docs?.querySelector('.doc-grid')).toBeNull();
  });

  it('drops the compact treatment once a document exists', async () => {
    mockGet.mockResolvedValue(TRIP);
    mockDocList.mockResolvedValue([
      { id: 'doc-1', trip_id: 'trip-1', filename: 'visa.pdf', page_count: 1 },
    ]);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });

    await waitFor(() => expect(container.querySelector('.doc-grid')).toBeInTheDocument());
    const docs = container.querySelector('.doc-grid')?.closest('.trip-section');
    expect(docs).not.toHaveClass('trip-section-compact');
    expect(docs?.querySelector('.section-note')).toBeNull();
  });

  it('keeps the rating stars on the section header row', async () => {
    mockGet.mockResolvedValue(TRIP);
    const { container } = render(TripDetailPage, { props: { params: { id: 'trip-1' } } });
    await waitFor(() =>
      expect(container.querySelector('.trip-rating-stars')).toBeInTheDocument(),
    );
    expect(
      container.querySelector('.trip-section-header .trip-rating-stars'),
    ).toBeInTheDocument();
  });
});
