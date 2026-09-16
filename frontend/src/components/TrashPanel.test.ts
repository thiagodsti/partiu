import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockList, mockRestore, mockPurge } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockRestore: vi.fn(),
  mockPurge: vi.fn(),
}));

vi.mock('../api/client', () => ({
  trashApi: { list: mockList, restore: mockRestore, purge: mockPurge },
}));

vi.mock('../lib/i18n', async () => {
  const { readable } = await import('svelte/store');
  return {
    t: readable((key: string, opts?: { values?: Record<string, unknown> }) => {
      const v = opts?.values ?? {};
      return Object.keys(v).length ? `${key}:${Object.values(v).join(',')}` : key;
    }),
  };
});

import TrashPanel from './TrashPanel.svelte';

const tripItem = {
  id: 7,
  kind: 'trip' as const,
  entity_id: 'trip-1',
  label: 'Stockholm → Reykjavík (Apr 2026)',
  summary: { start_date: '2026-04-02', end_date: '2026-04-08', flight_count: 4, rating: 4.5 },
  deleted_at: '2026-09-16T10:00:00+00:00',
};

describe('TrashPanel', () => {
  beforeEach(() => {
    mockList.mockReset();
    mockRestore.mockReset();
    mockPurge.mockReset();
  });

  it('shows the empty state when nothing is trashed', async () => {
    mockList.mockResolvedValue([]);
    render(TrashPanel);
    await waitFor(() => expect(screen.getByText('trash.empty')).toBeTruthy());
  });

  it('lists a trashed trip with its label and contents', async () => {
    mockList.mockResolvedValue([tripItem]);
    render(TrashPanel);
    await waitFor(() => expect(screen.getByText('Stockholm → Reykjavík (Apr 2026)')).toBeTruthy());
    expect(screen.getByText(/trash\.n_flights:4/)).toBeTruthy();
    expect(screen.getByText(/★ 4\.5/)).toBeTruthy();
  });

  it('restore calls the API, removes the row and reports skipped items', async () => {
    mockList.mockResolvedValue([tripItem]);
    mockRestore.mockResolvedValue({
      kind: 'trip',
      entity_id: 'trip-1',
      label: tripItem.label,
      restored: { trips: 1 },
      skipped: { flights: 2 },
    });
    render(TrashPanel);
    await waitFor(() => screen.getByText('trash.restore'));
    await fireEvent.click(screen.getByText('trash.restore'));
    await waitFor(() => expect(mockRestore).toHaveBeenCalledWith(7));
    await waitFor(() => expect(screen.queryByText(tripItem.label)).toBeNull());
    expect(screen.getByRole('status').textContent).toContain('trash.restored_with_skips');
    expect(screen.getByRole('status').textContent).toContain('2');
  });

  it('purge asks first and does nothing when declined', async () => {
    mockList.mockResolvedValue([tripItem]);
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(false));
    render(TrashPanel);
    await waitFor(() => screen.getByText('trash.purge'));
    await fireEvent.click(screen.getByText('trash.purge'));
    expect(mockPurge).not.toHaveBeenCalled();
    expect(screen.getByText(tripItem.label)).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it('surfaces an API failure instead of hanging on loading', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    render(TrashPanel);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('boom'));
  });
});
