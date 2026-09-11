import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import { currentUser } from '../lib/authStore';
import type { Flight } from '../api/types';
import TripMap from './TripMap.svelte';

const { tileLayer, mockGetAirport, dragging, removeLayer } = vi.hoisted(() => ({
  tileLayer: vi.fn(),
  mockGetAirport: vi.fn(),
  dragging: { enable: vi.fn(), disable: vi.fn() },
  removeLayer: vi.fn(),
}));

type FakeLayer = { fire: (name: string) => void; addTo: ReturnType<typeof vi.fn> };

/** Minimal Leaflet stand-in: enough surface for the component to build a map
 * without a real DOM renderer, so the assertions can be about which tile
 * layers it chose. */
vi.mock('leaflet', () => {
  const layer = () => ({ on: vi.fn(), addTo: vi.fn(), remove: vi.fn() });
  const eventLayer = () => {
    const handlers: Record<string, (() => void)[]> = {};
    return {
      handlers,
      on: vi.fn((name: string, fn: () => void) => {
        (handlers[name] ??= []).push(fn);
      }),
      fire: (name: string) => (handlers[name] ?? []).forEach((fn) => fn()),
      addTo: vi.fn(),
      remove: vi.fn(),
    };
  };
  return {
    map: vi.fn(() => ({
      fitBounds: vi.fn(),
      removeLayer,
      remove: vi.fn(),
      invalidateSize: vi.fn(),
      dragging,
    })),
    tileLayer: tileLayer.mockImplementation(eventLayer),
    polyline: vi.fn(layer),
    marker: vi.fn(() => ({ bindTooltip: vi.fn(() => ({ addTo: vi.fn() })) })),
    divIcon: vi.fn(),
    latLng: vi.fn((lat: number, lon: number) => ({ lat, lon })),
    latLngBounds: vi.fn(),
    Browser: { touch: false },
  };
});

vi.mock('../api/client', () => ({ airportsApi: { get: mockGetAirport } }));

vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (key: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

// Only the fields the map reads; the rest never leaves the component.
const FLIGHT = {
  id: 'f1',
  departure_airport: 'GRU',
  arrival_airport: 'LHR',
} as Flight;

/** The URL passed to every L.tileLayer() call, in order. */
function tileUrls(): string[] {
  return tileLayer.mock.calls.map((call) => call[0] as string);
}

describe('TripMap tile layers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAirport.mockImplementation((code: string) =>
      Promise.resolve({
        iata_code: code,
        name: code,
        city_name: code,
        latitude: 1,
        longitude: 2,
      }),
    );
  });

  it('uses OpenStreetMap tiles only when no CARTO key is configured', async () => {
    currentUser.set({ id: '1', username: 'u', is_admin: false, smtp_recipient_address: null });
    render(TripMap, { props: { flights: [FLIGHT] } });

    await waitFor(() => expect(tileLayer).toHaveBeenCalled());
    const urls = tileUrls();
    expect(urls.some((u) => u.includes('tile.openstreetmap.org'))).toBe(true);
    // An unkeyed CARTO layer would render the "API KEY REQUIRED" watermark.
    expect(urls.some((u) => u.includes('cartocdn.com'))).toBe(false);
  });

  it('uses CARTO Voyager tiles with the key when one is configured', async () => {
    currentUser.set({
      id: '1',
      username: 'u',
      is_admin: false,
      smtp_recipient_address: null,
      carto_api_key: 'abc 123',
    });
    render(TripMap, { props: { flights: [FLIGHT] } });

    await waitFor(() => expect(tileLayer).toHaveBeenCalled());
    const carto = tileUrls().find((u) => u.includes('cartocdn.com'));
    expect(carto).toBeDefined();
    expect(carto).toContain('rastertiles/voyager');
    expect(carto).toContain('?key=abc%20123');
  });
});

describe('TripMap pan toggle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentUser.set({ id: '1', username: 'u', is_admin: false, smtp_recipient_address: null });
    mockGetAirport.mockResolvedValue({
      iata_code: 'GRU',
      name: 'GRU',
      city_name: 'GRU',
      latitude: 1,
      longitude: 2,
    });
  });

  it('turns dragging off and back on without rebuilding the map', async () => {
    const L = await import('leaflet');
    const { getByRole } = render(TripMap, { props: { flights: [FLIGHT] } });

    await waitFor(() => expect(L.map).toHaveBeenCalledTimes(1));
    // happy-dom reports no touch, so the map starts pannable, as on desktop.
    expect(vi.mocked(L.map).mock.calls[0][1]?.dragging).toBe(true);

    const toggle = getByRole('button', { name: /map\.lock/ });
    await fireEvent.click(toggle);
    expect(dragging.disable).toHaveBeenCalled();

    await fireEvent.click(getByRole('button', { name: /map\.unlock/ }));
    expect(dragging.enable).toHaveBeenCalled();

    // Toggling must not tear the map down — it is read with untrack precisely
    // so the effect does not treat it as a dependency.
    expect(L.map).toHaveBeenCalledTimes(1);
  });
});

describe('TripMap basemap fallback', () => {
  /** The layers the component built, in creation order: OSM first, then CARTO. */
  function layers() {
    const results = tileLayer.mock.results.map((r) => r.value as FakeLayer);
    return { osm: results[0], carto: results[1] };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    currentUser.set({
      id: '1',
      username: 'u',
      is_admin: false,
      smtp_recipient_address: null,
      carto_api_key: 'k',
    });
    mockGetAirport.mockResolvedValue({
      iata_code: 'GRU',
      name: 'GRU',
      city_name: 'GRU',
      latitude: 1,
      longitude: 2,
    });
  });

  it('keeps CARTO when a few tiles drop but others load', async () => {
    render(TripMap, { props: { flights: [FLIGHT] } });
    await waitFor(() => expect(tileLayer).toHaveBeenCalledTimes(2));
    const { osm, carto } = layers();

    carto.fire('tileload');
    for (let i = 0; i < 10; i++) carto.fire('tileerror');

    // A reachable basemap is never demoted — OSM's labels are in the local
    // language, so falling back mid-session changes what the map says.
    expect(removeLayer).not.toHaveBeenCalled();
    expect(osm.addTo).not.toHaveBeenCalled();
  });

  it('tolerates a burst of failures before any tile has loaded', async () => {
    render(TripMap, { props: { flights: [FLIGHT] } });
    await waitFor(() => expect(tileLayer).toHaveBeenCalledTimes(2));
    const { osm, carto } = layers();

    carto.fire('tileerror');
    carto.fire('tileerror');
    carto.fire('tileerror');

    expect(osm.addTo).not.toHaveBeenCalled();
  });

  it('falls back to OSM when every tile fails, as when CARTO is blocked', async () => {
    render(TripMap, { props: { flights: [FLIGHT] } });
    await waitFor(() => expect(tileLayer).toHaveBeenCalledTimes(2));
    const { osm, carto } = layers();

    for (let i = 0; i < 4; i++) carto.fire('tileerror');

    expect(removeLayer).toHaveBeenCalledTimes(1);
    expect(osm.addTo).toHaveBeenCalledTimes(1);

    // ...and the swap happens once, however many more tiles fail after it.
    for (let i = 0; i < 6; i++) carto.fire('tileerror');
    expect(osm.addTo).toHaveBeenCalledTimes(1);
  });
});
