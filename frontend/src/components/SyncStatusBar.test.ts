import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import SyncStatusBar from './SyncStatusBar.svelte';
import type { SyncStatus } from '../api/types';

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string, opts?: unknown) => string) => void) => {
      fn((k: string, opts?: unknown) => {
        const o = opts as { values?: Record<string, string> } | undefined;
        if (o?.values) {
          return Object.entries(o.values).reduce(
            (s, [k2, v]) => s.replace(`{${k2}}`, String(v)),
            k,
          );
        }
        return k;
      });
      return () => {};
    },
  },
}));

vi.mock('../lib/utils', () => ({
  formatDateTimeLocale: (v: string | null | undefined) => v ?? 'never',
}));

const BASE: SyncStatus = {
  status: 'idle',
  last_synced_at: '2025-01-01T12:00:00Z',
  last_error: null,
  sync_interval_minutes: 60,
};

describe('SyncStatusBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders idle state with last sync time', () => {
    const { container } = render(SyncStatusBar, { props: { syncStatus: BASE } });
    expect(container.querySelector('.sync-dot.idle')).toBeInTheDocument();
    expect(container.textContent).toContain('sync.last_sync');
  });

  it('renders running state', () => {
    const { container } = render(SyncStatusBar, {
      props: { syncStatus: { ...BASE, status: 'running' } },
    });
    expect(container.querySelector('.sync-dot.running')).toBeInTheDocument();
    expect(container.textContent).toContain('sync.running');
  });

  it('renders error state with error message', () => {
    const { container } = render(SyncStatusBar, {
      props: { syncStatus: { ...BASE, status: 'error', last_error: 'connection refused' } },
    });
    expect(container.querySelector('.sync-dot.error')).toBeInTheDocument();
    expect(container.textContent).toContain('sync.error');
    expect(container.textContent).toContain('connection refused');
  });

  it('renders never synced when last_synced_at is null', () => {
    const { container } = render(SyncStatusBar, {
      props: { syncStatus: { ...BASE, last_synced_at: null } },
    });
    expect(container.textContent).toContain('sync.never');
  });

  it('renders never synced when syncStatus is null', () => {
    const { container } = render(SyncStatusBar, { props: { syncStatus: null } });
    expect(container.textContent).toContain('sync.never');
  });

  it('applies id prop to the wrapper div', () => {
    const { container } = render(SyncStatusBar, {
      props: { syncStatus: BASE, id: 'my-bar' },
    });
    expect(container.querySelector('#my-bar')).toBeInTheDocument();
  });

  it('applies style prop to the wrapper div', () => {
    const { container } = render(SyncStatusBar, {
      props: { syncStatus: BASE, style: 'margin-bottom:8px' },
    });
    const bar = container.querySelector('.sync-status-bar') as HTMLElement;
    expect(bar?.getAttribute('style')).toMatch(/margin-bottom/);
  });

  it('shows next sync label when interval is set and not running', () => {
    // Set last_synced_at far in the past so next sync is overdue → nextSyncLabel is non-null
    const { container } = render(SyncStatusBar, {
      props: {
        syncStatus: {
          ...BASE,
          last_synced_at: new Date(Date.now() - 200 * 60 * 1000).toISOString(),
          sync_interval_minutes: 60,
        },
      },
    });
    // nextSyncLabel is non-null, so sync.next_sync wrapper is rendered
    expect(container.textContent).toContain('sync.next_sync');
  });
});
