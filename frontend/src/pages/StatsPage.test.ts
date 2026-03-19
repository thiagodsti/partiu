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

  it('shows empty state when total_flights is 0', async () => {
    mockGet.mockResolvedValue({ ...STATS, total_flights: 0 });
    const { container } = render(StatsPage);
    await waitFor(() => expect(container.textContent).toContain('stats.empty'));
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
});
