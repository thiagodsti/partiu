import { render, screen, waitFor } from '@testing-library/svelte';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockList } = vi.hoisted(() => ({ mockList: vi.fn() }));

vi.mock('../api/client', () => ({ activityApi: { list: mockList } }));

vi.mock('../lib/i18n', async () => {
  const { readable } = await import('svelte/store');
  return {
    t: readable((key: string, opts?: { values?: Record<string, unknown> }) => {
      const v = opts?.values ?? {};
      return `${key}|${v.label ?? ''}|${v.source ?? ''}|${v.from ?? ''}|${v.to ?? ''}`;
    }),
  };
});

import ActivityPanel from './ActivityPanel.svelte';

describe('ActivityPanel', () => {
  beforeEach(() => mockList.mockReset());

  it('renders each known action through its own string', async () => {
    mockList.mockResolvedValue([
      { id: 3, action: 'sync.rescan', entity_type: null, entity_id: null, label: null, details: { from_version: '33', to_version: '35', since: '2026-06-18' }, created_at: '2026-09-16T10:00:00+00:00' },
      { id: 2, action: 'trips.merged', entity_type: 'trip', entity_id: 't2', label: 'Target', details: { source_name: 'Source' }, created_at: '2026-09-15T10:00:00+00:00' },
      { id: 1, action: 'trip.trashed', entity_type: 'trip', entity_id: 't1', label: 'Reykjavík', details: {}, created_at: '2026-09-14T10:00:00+00:00' },
    ]);
    render(ActivityPanel);
    await waitFor(() => expect(screen.getByText(/activity\.trip_trashed\|Reykjavík/)).toBeTruthy());
    expect(screen.getByText(/activity\.trips_merged\|Target\|Source/)).toBeTruthy();
    expect(screen.getByText(/activity\.sync_rescan\|\|\|33\|35/)).toBeTruthy();
  });

  it('falls back to a generic line for an action it does not know', async () => {
    mockList.mockResolvedValue([
      { id: 1, action: 'something.new', entity_type: null, entity_id: null, label: 'x', details: {}, created_at: '2026-09-14T10:00:00+00:00' },
    ]);
    render(ActivityPanel);
    await waitFor(() => expect(screen.getByText(/activity\.unknown\|x/)).toBeTruthy());
  });

  it('shows the empty state', async () => {
    mockList.mockResolvedValue([]);
    render(ActivityPanel);
    await waitFor(() => expect(screen.getByText(/activity\.empty/)).toBeTruthy());
  });
});
