import { writable } from 'svelte/store';

// Maps trip_id -> cache-bust timestamp. Shared across all pages so a refresh
// on the list immediately propagates to the detail page and vice versa.
const _bust = writable<Record<string, number>>({});

export const tripImageBust = {
  subscribe: _bust.subscribe,
  bust(tripId: string) {
    _bust.update(m => ({ ...m, [tripId]: Date.now() }));
  },
  urlFor(tripId: string, bust: Record<string, number>): string {
    const t = bust[tripId];
    return `/api/trips/${tripId}/image${t ? `?t=${t}` : ''}`;
  },
};
