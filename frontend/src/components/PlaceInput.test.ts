import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import PlaceInput from './PlaceInput.svelte';

const { mockCities, mockStations, mockPlaces } = vi.hoisted(() => ({
  mockCities: vi.fn(),
  mockStations: vi.fn(),
  mockPlaces: vi.fn(),
}));

vi.mock('../api/client', () => ({
  citiesApi: { search: mockCities },
  stationsApi: { search: mockStations },
  placesApi: { search: mockPlaces },
}));

vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (k: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

function place(name: string, city: string, lat: number, lon: number) {
  return {
    name,
    city,
    address: '',
    country: 'Brazil',
    countrycode: 'BR',
    category: 'place' as const,
    lat,
    lon,
  };
}

const props = {
  value: '',
  lat: null,
  lon: null,
  kind: 'city' as const,
  onchange: () => {},
};

describe('PlaceInput', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCities.mockResolvedValue([]);
    mockStations.mockResolvedValue([]);
    mockPlaces.mockResolvedValue([]);
  });

  /* Photon returns the same node twice under different labels: "Rio de Janeiro"
   * gives Itaboraí once as its own city and once with the state as its city, at
   * byte-identical coordinates. The list used to be keyed on that coordinate
   * pair, and a duplicate key is a hard error in Svelte — it took the whole page
   * down behind the app's error boundary ("This page didn't load."). */
  it('renders results that share a coordinate pair without throwing', async () => {
    mockCities.mockResolvedValue([
      place('Itaboraí', 'Itaboraí', -22.7496231, -42.8557428),
      place('Itaboraí', 'Rio de Janeiro', -22.7496231, -42.8557428),
    ]);
    const { container } = render(PlaceInput, { props });

    await fireEvent.input(container.querySelector('input')!, {
      target: { value: 'Rio de Janeiro' },
    });

    await waitFor(() => expect(container.querySelectorAll('.station-result')).toHaveLength(2), {
      timeout: 2000,
    });
  });

  it('searches cities through the city endpoint', async () => {
    const { container } = render(PlaceInput, { props });

    await fireEvent.input(container.querySelector('input')!, { target: { value: 'Belém' } });

    await waitFor(() => expect(mockCities).toHaveBeenCalledWith('Belém'), { timeout: 2000 });
    expect(mockStations).not.toHaveBeenCalled();
  });

  // A city's `address` is the city itself ("Oslo" under "Oslo"), which
  // distinguishes nothing; the country is what separates Oslo from Oslo.
  it('labels a city with its region and country, not its address', async () => {
    mockCities.mockResolvedValue([
      { ...place('Oslo', 'Marshall', 48.195, -97.131), country: 'United States', address: 'Marshall' },
    ]);
    const { container } = render(PlaceInput, { props });

    await fireEvent.input(container.querySelector('input')!, { target: { value: 'Oslo' } });

    await waitFor(() => expect(container.querySelector('.station-where')).toBeInTheDocument(), {
      timeout: 2000,
    });
    expect(container.querySelector('.station-where')?.textContent).toBe('Marshall, United States');
  });

  it('drops the region from the label when it just repeats the name', async () => {
    mockCities.mockResolvedValue([
      { ...place('Oslo', 'Oslo', 59.97, 10.77), country: 'Norway' },
    ]);
    const { container } = render(PlaceInput, { props });

    await fireEvent.input(container.querySelector('input')!, { target: { value: 'Oslo' } });

    await waitFor(() => expect(container.querySelector('.station-where')).toBeInTheDocument(), {
      timeout: 2000,
    });
    expect(container.querySelector('.station-where')?.textContent).toBe('Norway');
  });

  it('leaves what was typed in place when the geocoder fails', async () => {
    mockCities.mockRejectedValue(new Error('offline'));
    const { container } = render(PlaceInput, { props });

    await fireEvent.input(container.querySelector('input')!, { target: { value: 'Belém' } });

    await waitFor(() => expect(container.querySelector('.station-hint')).toBeInTheDocument(), {
      timeout: 2000,
    });
    expect(container.querySelectorAll('.station-result')).toHaveLength(0);
  });
});
