import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import HistoryPage from './HistoryPage.svelte';

const { mockList, mockSettingsGet, mockRefreshImage, mockCreateImmichAlbum } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockSettingsGet: vi.fn(),
  mockRefreshImage: vi.fn(),
  mockCreateImmichAlbum: vi.fn(),
}));

vi.mock('../api/client', () => ({
  tripsApi: {
    list: mockList,
    refreshImage: mockRefreshImage,
    createImmichAlbum: mockCreateImmichAlbum,
  },
  settingsApi: { get: mockSettingsGet },
}));

// ImmichAlbumButton uses ../api/client directly — already mocked above

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

const COMPLETED_TRIP = {
  id: 'trip-1',
  name: 'Rome 2024',
  start_date: '2024-05-01',
  end_date: '2024-05-10',
  origin_airport: 'GRU',
  destination_airport: 'FCO',
  booking_refs: ['RM001'],
  flight_count: 2,
  immich_album_id: null,
};

const SETTINGS_NO_IMMICH = {
  immich_url: null,
  immich_api_key_set: false,
};

const SETTINGS_WITH_IMMICH = {
  immich_url: 'https://immich.local',
  immich_api_key_set: true,
};

describe('HistoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({ trips: [COMPLETED_TRIP] });
    mockSettingsGet.mockResolvedValue(SETTINGS_NO_IMMICH);
  });

  it('shows loading screen initially', () => {
    mockList.mockReturnValue(new Promise(() => {}));
    mockSettingsGet.mockReturnValue(new Promise(() => {}));
    const { container } = render(HistoryPage);
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('renders completed trip card', async () => {
    const { findByText } = render(HistoryPage);
    expect(await findByText('Rome 2024')).toBeInTheDocument();
  });

  it('shows empty state when no completed trips exist', async () => {
    mockList.mockResolvedValue({ trips: [] });
    const { container } = render(HistoryPage);
    await waitFor(() =>
      expect(container.querySelector('.empty-state')).toBeInTheDocument(),
    );
  });

  it('shows empty state when all trips are upcoming', async () => {
    const upcomingTrip = {
      ...COMPLETED_TRIP,
      start_date: '2099-01-01',
      end_date: '2099-01-10',
    };
    mockList.mockResolvedValue({ trips: [upcomingTrip] });
    const { container } = render(HistoryPage);
    await waitFor(() =>
      expect(container.querySelector('.empty-state')).toBeInTheDocument(),
    );
  });

  it('shows load error when API fails', async () => {
    mockList.mockRejectedValue(new Error('Load failed'));
    const { findByText } = render(HistoryPage);
    expect(await findByText('Load failed')).toBeInTheDocument();
  });

  it('does not show Immich button when Immich is not configured', async () => {
    const { container } = render(HistoryPage);
    await waitFor(() => expect(container.querySelector('.trip-card')).toBeInTheDocument());
    // There should be no Immich-specific button
    const buttons = Array.from(container.querySelectorAll('button'));
    const immichBtn = buttons.find((b) => b.textContent?.includes('Immich'));
    expect(immichBtn).toBeUndefined();
  });

  it('shows Create Immich Album button when Immich is configured', async () => {
    mockSettingsGet.mockResolvedValue(SETTINGS_WITH_IMMICH);
    const { findByText } = render(HistoryPage);
    // t() mock returns the key
    expect(await findByText('immich.create_album')).toBeInTheDocument();
  });

  it('shows Open Immich Album button when album already exists', async () => {
    mockSettingsGet.mockResolvedValue(SETTINGS_WITH_IMMICH);
    mockList.mockResolvedValue({
      trips: [{ ...COMPLETED_TRIP, immich_album_id: 'album-abc' }],
    });
    const { findByText } = render(HistoryPage);
    expect(await findByText('immich.open_album')).toBeInTheDocument();
  });

  it('calls tripsApi.createImmichAlbum when Create button is clicked', async () => {
    mockSettingsGet.mockResolvedValue(SETTINGS_WITH_IMMICH);
    mockCreateImmichAlbum.mockResolvedValue({ album_id: 'new-album', album_url: null });
    const { findByText } = render(HistoryPage);

    const btn = await findByText('immich.create_album');
    await fireEvent.click(btn);
    await waitFor(() => expect(mockCreateImmichAlbum).toHaveBeenCalledWith('trip-1'));
  });

  it('card links point to /history/:id', async () => {
    const { container } = render(HistoryPage);
    await waitFor(() => expect(container.querySelector('.card-link')).toBeInTheDocument());
    const link = container.querySelector('a.card-link') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('#/history/trip-1');
  });
});
