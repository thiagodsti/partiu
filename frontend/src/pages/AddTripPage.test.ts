import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import AddTripPage from './AddTripPage.svelte';

const { mockPush, mockCreate } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockCreate: vi.fn(),
}));

vi.mock('svelte-spa-router', () => ({ push: mockPush }));
vi.mock('../api/client', () => ({
  tripsApi: { create: mockCreate },
  airportsApi: { search: vi.fn().mockResolvedValue([]) },
  citiesApi: { search: vi.fn().mockResolvedValue([]) },
  stationsApi: { search: vi.fn().mockResolvedValue([]) },
  placesApi: { search: vi.fn().mockResolvedValue([]) },
}));

// i18n: return key as value so tests work without real translations
vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (key: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

function getNameInput(container: HTMLElement) {
  // The trip name field is the first text input in the form
  return container.querySelector('input[type="text"][required]') as HTMLInputElement;
}

describe('AddTripPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders form with required name field', () => {
    const { container } = render(AddTripPage);
    const nameInput = getNameInput(container);
    expect(nameInput).toBeInTheDocument();
    expect(nameInput.required).toBe(true);
  });

  it('renders two date inputs', () => {
    const { container } = render(AddTripPage);
    const dateInputs = container.querySelectorAll('input[type="date"]');
    expect(dateInputs).toHaveLength(2);
  });

  // A trip's route is derived from the legs you add to it — `_recompute_span`
  // rewrites origin and destination from the flights and nulls them when there
  // are none — so asking for airports at creation was asking for something the
  // first leg would erase, and meaningless for a rail trip besides.
  it('does not ask for a route', () => {
    const { container } = render(AddTripPage);
    expect(container.querySelectorAll('.airport-combobox')).toHaveLength(0);
  });

  it('renders cancel link pointing to /trips', () => {
    const { container } = render(AddTripPage);
    const cancelLink = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(cancelLink).toBeInTheDocument();
    expect(cancelLink.getAttribute('href')).toBe('#/trips');
  });

  it('renders submit button', () => {
    const { container } = render(AddTripPage);
    const submitBtn = container.querySelector('button[type="submit"]');
    expect(submitBtn).toBeInTheDocument();
  });

  it('calls tripsApi.create with trimmed name on submit', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-123' });
    const { container } = render(AddTripPage);

    await fireEvent.input(getNameInput(container), { target: { value: '  Paris 2025  ' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Paris 2025' }),
      );
    });
  });

  // A booking reference belongs to the leg it was issued for, and that is where
  // it is now typed. The trip-level list is written by auto-grouping; asking for
  // it by hand offered nothing, since every grouping read of it is gated on
  // `is_auto_generated = 1` and so never fires for a trip you created yourself.
  it('does not ask for booking references', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-789' });
    const { container } = render(AddTripPage);
    // Not `input[autocomplete="off"]` — the city pickers carry that too.
    expect(container.textContent).not.toContain('add_trip.booking_refs');

    await fireEvent.input(getNameInput(container), { target: { value: 'No Refs Trip' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    expect(mockCreate.mock.calls[0][0]).not.toHaveProperty('booking_refs');
  });

  // A trip's ends are places, not airport codes: a Florianópolis → São Paulo
  // drive has both and neither is an airport. They are their own columns, since
  // `origin_airport`/`destination_airport` are derived from the flights.
  it('asks for the ends as cities, not airports', () => {
    const { container } = render(AddTripPage);
    expect(container.querySelectorAll('.station-input')).toHaveLength(2);
    expect(container.querySelectorAll('.airport-combobox')).toHaveLength(0);
  });

  it('sends the typed ends as places', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-101' });
    const { container } = render(AddTripPage);

    await fireEvent.input(getNameInput(container), { target: { value: 'Ano novo' } });
    const places = container.querySelectorAll('.station-input input');
    await fireEvent.input(places[0], { target: { value: 'Florianópolis' } });
    await fireEvent.input(places[1], { target: { value: 'São Paulo' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          origin: expect.objectContaining({ name: 'Florianópolis' }),
          destinations: [expect.objectContaining({ name: 'São Paulo' })],
        }),
      ),
    );
  });

  // A trip goes to more than one place, and the form has to let you say so.
  it('collects several destinations and drops the blank rows', async () => {
    mockCreate.mockResolvedValue({ id: 'trip-102' });
    const { container } = render(AddTripPage);

    await fireEvent.input(getNameInput(container), { target: { value: 'Brasil' } });
    await fireEvent.click(container.querySelector('.destination-add')!);
    // A third row is added and deliberately left empty.
    await fireEvent.click(container.querySelector('.destination-add')!);

    const places = container.querySelectorAll('.station-input input');
    await fireEvent.input(places[1], { target: { value: 'São Paulo' } });
    await fireEvent.input(places[2], { target: { value: 'Rio de Janeiro' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    expect(mockCreate.mock.calls[0][0].destinations.map((d: { name: string }) => d.name)).toEqual([
      'São Paulo',
      'Rio de Janeiro',
    ]);
  });

  it('can remove a destination row', async () => {
    const { container } = render(AddTripPage);
    await fireEvent.click(container.querySelector('.destination-add')!);
    expect(container.querySelectorAll('.destination-row')).toHaveLength(2);

    await fireEvent.click(container.querySelectorAll('.destination-remove')[0]);
    expect(container.querySelectorAll('.destination-row')).toHaveLength(1);
  });

  it('shows error message when API fails', async () => {
    mockCreate.mockRejectedValue(new Error('Server error'));
    const { container, findByText } = render(AddTripPage);

    await fireEvent.change(getNameInput(container), { target: { value: 'Failing Trip' } });
    await fireEvent.submit(container.querySelector('form')!);

    const errorMsg = await findByText('Server error');
    expect(errorMsg).toBeInTheDocument();
  });

  it('navigates to new trip on success', async () => {
    mockCreate.mockResolvedValue({ id: 'new-trip-id' });
    const { container } = render(AddTripPage);

    await fireEvent.change(getNameInput(container), { target: { value: 'Success Trip' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/trips/new-trip-id');
    });
  });
});
