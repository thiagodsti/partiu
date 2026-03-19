import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import AddFlightPage from './AddFlightPage.svelte';

const { mockPush, mockCreate } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockCreate: vi.fn(),
}));

vi.mock('svelte-spa-router', () => ({ push: mockPush }));
vi.mock('../api/client', () => ({
  flightsApi: { create: mockCreate },
  airportsApi: { search: vi.fn().mockResolvedValue([]) },
}));

// i18n: return key as value so tests work without real translations
vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (key: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

const DEFAULT_PARAMS = { tripId: 'trip-42' };

/** Fill the three required fields so the form can be submitted. */
async function fillRequired(container: HTMLElement) {
  // Flight number: first input[required] that isn't inside a combobox
  const allRequired = container.querySelectorAll('input[required]');
  const flightNumInput = allRequired[0] as HTMLInputElement;
  await fireEvent.input(flightNumInput, { target: { value: 'LA800' } });

  const dateInputs = container.querySelectorAll('input[type="datetime-local"]');
  await fireEvent.change(dateInputs[0], { target: { value: '2025-06-01T10:00' } });
  await fireEvent.change(dateInputs[1], { target: { value: '2025-06-01T14:00' } });

  // Airport combobox inputs
  const comboboxInputs = container.querySelectorAll('.airport-combobox input');
  await fireEvent.input(comboboxInputs[0], { target: { value: 'GRU' } });
  await fireEvent.input(comboboxInputs[1], { target: { value: 'SCL' } });
}

describe('AddFlightPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders at least 4 form sections', () => {
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });
    const sections = container.querySelectorAll('.form-section');
    expect(sections.length).toBeGreaterThanOrEqual(4);
  });

  it('renders required flight number input', () => {
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });
    const flightNumInput = container.querySelector('input.mono[required]');
    expect(flightNumInput).toBeInTheDocument();
  });

  it('renders two datetime-local inputs (departure and arrival)', () => {
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });
    const dtInputs = container.querySelectorAll('input[type="datetime-local"]');
    expect(dtInputs).toHaveLength(2);
  });

  it('renders two airport comboboxes (departure and arrival)', () => {
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });
    const comboboxes = container.querySelectorAll('.airport-combobox');
    expect(comboboxes).toHaveLength(2);
  });

  it('cancel link points back to the trip', () => {
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });
    const cancelLink = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(cancelLink).toBeInTheDocument();
    expect(cancelLink.getAttribute('href')).toBe('#/trips/trip-42');
  });

  it('renders cabin class select with 5 options', () => {
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });
    const select = container.querySelector('select');
    expect(select).toBeInTheDocument();
    expect(select!.querySelectorAll('option')).toHaveLength(5);
  });

  it('calls flightsApi.create with trip_id on submit', async () => {
    mockCreate.mockResolvedValue({ id: 'flight-1', trip_id: 'trip-42' });
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });

    await fillRequired(container);
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ trip_id: 'trip-42' }),
      );
    });
  });

  it('uppercases flight number on submit', async () => {
    mockCreate.mockResolvedValue({ id: 'flight-2', trip_id: 'trip-42' });
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });

    const flightNumInput = container.querySelector('input.mono[required]') as HTMLInputElement;
    await fireEvent.input(flightNumInput, { target: { value: 'la800' } });

    const dateInputs = container.querySelectorAll('input[type="datetime-local"]');
    await fireEvent.change(dateInputs[0], { target: { value: '2025-06-01T10:00' } });
    await fireEvent.change(dateInputs[1], { target: { value: '2025-06-01T14:00' } });

    const comboboxInputs = container.querySelectorAll('.airport-combobox input');
    await fireEvent.input(comboboxInputs[0], { target: { value: 'gru' } });
    await fireEvent.input(comboboxInputs[1], { target: { value: 'scl' } });

    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          flight_number: 'LA800',
          departure_airport: 'GRU',
          arrival_airport: 'SCL',
        }),
      );
    });
  });

  it('shows error message when API fails', async () => {
    mockCreate.mockRejectedValue(new Error('Flight already exists'));
    const { container, findByText } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });

    await fillRequired(container);
    await fireEvent.submit(container.querySelector('form')!);

    const errorMsg = await findByText('Flight already exists');
    expect(errorMsg).toBeInTheDocument();
  });

  it('navigates to trip page on success', async () => {
    mockCreate.mockResolvedValue({ id: 'flight-ok', trip_id: 'trip-42' });
    const { container } = render(AddFlightPage, { props: { params: DEFAULT_PARAMS } });

    await fillRequired(container);
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/trips/trip-42');
    });
  });
});
