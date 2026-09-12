import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import StatsPage from './StatsPage.svelte';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('../api/client', () => ({ statsApi: { get: mockGet } }));

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
  // Real store, not a stub: the hero resolves country codes to names through
  // Intl.DisplayNames using this locale, so omitting it silently exercised the
  // fallback path instead of the one users see.
  locale: writable('en'),
}));

vi.mock('svelte-i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const STATS = {
  years: [2024, 2025],
  total_km: 15000,
  total_flights: 10,
  total_hours: 25,
  unique_airports: 8,
  unique_countries: 5,
  visited_countries: ['SE', 'NO'],
  ground_legs: 0,
  nights_away: 0,
  longest_flight: { from: 'GRU', to: 'MIA', km: 7500 },
  top_routes: [{ key: 'GRU-MIA', count: 3 }],
  top_airports: [{ key: 'GRU', count: 5 }],
  top_airlines: [{ key: 'LA', count: 5 }, { key: 'AD', count: 3 }],
  distance_buckets: [],
  earth_laps: 0.37,
};

describe('StatsPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows loading screen initially', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    const { container } = render(StatsPage);
    expect(container.querySelector('.loading-screen')).toBeInTheDocument();
  });

  it('shows error when load fails', async () => {
    mockGet.mockRejectedValue(new Error('Server error'));
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('Server error'));
  });

  it('shows empty state when there is nothing at all', async () => {
    mockGet.mockResolvedValue({ ...STATS, total_flights: 0, unique_countries: 0 });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('stats.empty'));
  });

  it('renders stats for a rail-only account with no flights', async () => {
    // Ground legs and stays contribute countries but no flights, so keying the
    // empty state off the flight count alone hid a real Stockholm-Oslo trip.
    mockGet.mockResolvedValue({ ...STATS, total_flights: 0, unique_countries: 2 });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).not.toContain('stats.empty'));
    expect(container.textContent).toContain('stats.countries');
  });

  it('swaps the hero to countries when there are no flights', async () => {
    // "0 km" as the headline is technically true and tells a rail traveller
    // nothing, so the hero shows what they did do.
    mockGet.mockResolvedValue({
      ...STATS,
      total_flights: 0,
      total_km: 0,
      unique_countries: 2,
      visited_countries: ['SE', 'NO'],
    });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('stats.countries_visited'));
    expect(container.textContent).not.toContain('stats.total_distance');
    // Codes are rendered as names via Intl.DisplayNames.
    expect(container.textContent).toContain('Sweden');
  });

  it('keeps the km hero when there are flights', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('stats.total_distance'));
    expect(container.textContent).not.toContain('stats.countries_visited');
  });

  it('shows ground legs and nights away only when non-zero', async () => {
    mockGet.mockResolvedValue({ ...STATS, ground_legs: 3, nights_away: 7 });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('stats.ground_legs'));
    expect(container.textContent).toContain('stats.nights_away');
  });

  it('hides the ground cards for a flights-only account', async () => {
    mockGet.mockResolvedValue({ ...STATS, ground_legs: 0, nights_away: 0 });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('stats.flights'));
    expect(container.textContent).not.toContain('stats.ground_legs');
    expect(container.textContent).not.toContain('stats.nights_away');
  });

  it('renders total flights when stats are loaded', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('10'));
  });

  it('renders total distance', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('15'));
  });

  it('renders year pills when multiple years exist', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => {
      expect(container.querySelector('.year-pills')).toBeInTheDocument();
      expect(container.textContent).toContain('2024');
      expect(container.textContent).toContain('2025');
    });
  });

  it('does not show year pills when only one year', async () => {
    mockGet.mockResolvedValue({ ...STATS, years: [2025] });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.querySelector('.loading-screen')).not.toBeInTheDocument());
    expect(container.querySelector('.year-pills')).not.toBeInTheDocument();
  });

  it('calls statsApi.get with year when a year pill is clicked', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.querySelector('.year-pills')).toBeInTheDocument());

    const yearBtn = Array.from(container.querySelectorAll('.year-pill')).find(
      (b) => b.textContent?.includes('2024'),
    ) as HTMLButtonElement;
    await fireEvent.click(yearBtn);

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(2024));
  });

  it('countries link includes year query param when year is selected', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.querySelector('.year-pills')).toBeInTheDocument());

    // Select year 2024
    const yearBtn = Array.from(container.querySelectorAll('.year-pill')).find(
      (b) => b.textContent?.includes('2024'),
    ) as HTMLButtonElement;
    await fireEvent.click(yearBtn);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(2024));

    const mapLink = container.querySelector('.stat-card-link') as HTMLAnchorElement;
    expect(mapLink.getAttribute('href')).toBe('#/stats/map?year=2024');
  });

  it('countries link has no year param when all-time is selected', async () => {
    mockGet.mockResolvedValue(STATS);
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.querySelector('.stat-card-link')).toBeInTheDocument());

    const mapLink = container.querySelector('.stat-card-link') as HTMLAnchorElement;
    expect(mapLink.getAttribute('href')).toBe('#/stats/map');
  });
});
