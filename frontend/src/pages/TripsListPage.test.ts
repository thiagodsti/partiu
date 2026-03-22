import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import TripsListPage from './TripsListPage.svelte';

const { mockList, mockSyncStatus, mockSyncNow, mockRefreshImage, mockToastsShow, mockFailedEmailsList } = vi.hoisted(
  () => ({
    mockList: vi.fn(),
    mockSyncStatus: vi.fn(),
    mockSyncNow: vi.fn(),
    mockRefreshImage: vi.fn(),
    mockToastsShow: vi.fn(),
    mockFailedEmailsList: vi.fn(),
  }),
);

vi.mock('../api/client', () => ({
  tripsApi: { list: mockList, refreshImage: mockRefreshImage },
  syncApi: { status: mockSyncStatus, now: mockSyncNow },
  failedEmailsApi: { list: mockFailedEmailsList },
}));

vi.mock('../lib/toastStore', () => ({
  toasts: { show: mockToastsShow },
}));

vi.mock('../lib/tripImageStore', () => ({
  tripImageBust: {
    subscribe: (fn: (v: Record<string, number>) => void) => {
      fn({});
      return () => {};
    },
    bust: vi.fn(),
    urlFor: (_id: string) => '/api/trips/img',
  },
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string, opts?: unknown) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const TRIP = {
  id: 'trip-1',
  name: 'Paris Trip',
  start_date: '2026-06-01',
  end_date: '2026-06-10',
  origin_airport: 'GRU',
  destination_airport: 'CDG',
  booking_refs: [],
  flight_count: 2,
};

const SYNC_IDLE = {
  status: 'idle',
  last_synced_at: '2026-03-01T10:00:00Z',
  last_error: null,
  sync_interval_minutes: 10,
};

describe('TripsListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({ trips: [TRIP] });
    mockSyncStatus.mockResolvedValue(SYNC_IDLE);
    mockSyncNow.mockResolvedValue({});
    mockFailedEmailsList.mockResolvedValue([]);
  });

  it('shows loading screen initially', () => {
    mockList.mockReturnValue(new Promise(() => {}));
    mockSyncStatus.mockReturnValue(new Promise(() => {}));
    const { container } = render(TripsListPage);
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('renders trip cards after loading', async () => {
    const { findByText } = render(TripsListPage);
    expect(await findByText('Paris Trip')).toBeInTheDocument();
  });

  it('renders the sync status bar', async () => {
    const { container } = render(TripsListPage);
    await waitFor(() =>
      expect(container.querySelector('#sync-status-bar')).toBeInTheDocument(),
    );
  });

  it('renders new trip button', async () => {
    const { container } = render(TripsListPage);
    await waitFor(() => {
      const link = container.querySelector('a[href="#/trips/new"]');
      expect(link).toBeInTheDocument();
    });
  });

  it('shows empty state when no active trips', async () => {
    mockList.mockResolvedValue({ trips: [] });
    const { container } = render(TripsListPage);
    await waitFor(() =>
      expect(container.querySelector('.empty-state')).toBeInTheDocument(),
    );
  });

  it('shows error state when list fails', async () => {
    mockList.mockRejectedValue(new Error('Network error'));
    const { findByText } = render(TripsListPage);
    expect(await findByText('Network error')).toBeInTheDocument();
  });

  it('calls syncApi.now when sync button is clicked', async () => {
    const { container } = render(TripsListPage);
    await waitFor(() =>
      expect(container.querySelector('#sync-status-bar')).toBeInTheDocument(),
    );

    const syncBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('trips.btn_sync'),
    );
    expect(syncBtn).toBeInTheDocument();
    await fireEvent.click(syncBtn!);
    await waitFor(() => expect(mockSyncNow).toHaveBeenCalledOnce());
  });

  it('shows success toast when sync starts', async () => {
    const { container } = render(TripsListPage);
    await waitFor(() =>
      expect(container.querySelector('#sync-status-bar')).toBeInTheDocument(),
    );

    const syncBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('trips.btn_sync'),
    );
    await fireEvent.click(syncBtn!);
    await waitFor(() => {
      expect(mockToastsShow).toHaveBeenCalledWith('Sync started!', 'success');
    });
  });

  it('shows error toast when sync fails', async () => {
    mockSyncNow.mockRejectedValue(new Error('Sync error'));
    const { container } = render(TripsListPage);
    await waitFor(() =>
      expect(container.querySelector('#sync-status-bar')).toBeInTheDocument(),
    );

    const syncBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('trips.btn_sync'),
    );
    await fireEvent.click(syncBtn!);
    await waitFor(() => {
      expect(mockToastsShow).toHaveBeenCalledWith(
        expect.stringContaining('Sync failed'),
        'error',
      );
    });
  });

  it('completed trips do not appear in the active list', async () => {
    const completedTrip = {
      ...TRIP,
      id: 'trip-2',
      name: 'Old Trip',
      start_date: '2020-01-01',
      end_date: '2020-01-10',
    };
    mockList.mockResolvedValue({ trips: [completedTrip] });
    const { container } = render(TripsListPage);
    await waitFor(() =>
      expect(container.querySelector('.empty-state')).toBeInTheDocument(),
    );
  });
});
