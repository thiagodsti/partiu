import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import EditTripPage from './EditTripPage.svelte';

const { mockPush, mockGet, mockUpdate, mockRefreshImage } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockGet: vi.fn(),
  mockUpdate: vi.fn(),
  mockRefreshImage: vi.fn(),
}));

vi.mock('svelte-spa-router', () => ({ push: mockPush }));
vi.mock('../api/client', () => ({
  tripsApi: {
    get: mockGet,
    update: mockUpdate,
    refreshImage: mockRefreshImage,
  },
  airportsApi: { search: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const TRIP = {
  id: 'trip-99',
  name: 'Tokyo 2025',
  start_date: '2025-03-01',
  end_date: '2025-03-14',
  origin_airport: 'GRU',
  destination_airport: 'NRT',
  booking_refs: ['TK123'],
};

describe('EditTripPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue(TRIP);
    mockUpdate.mockResolvedValue({});
    mockRefreshImage.mockResolvedValue({});
  });

  it('shows loading state before trip loads', () => {
    mockGet.mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(EditTripPage, {
      props: { params: { id: 'trip-99' } },
    });
    expect(container.querySelector('.loading-placeholder')).toBeInTheDocument();
  });

  it('renders form with trip data after loading', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });

    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const nameInput = container.querySelector('input[type="text"][required]') as HTMLInputElement;
    expect(nameInput.value).toBe('Tokyo 2025');
  });

  it('shows load error when tripsApi.get fails', async () => {
    mockGet.mockRejectedValue(new Error('Not found'));
    const { findByText } = render(EditTripPage, { props: { params: { id: 'bad-id' } } });
    expect(await findByText('Not found')).toBeInTheDocument();
  });

  it('renders two date inputs pre-filled', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const dateInputs = container.querySelectorAll('input[type="date"]');
    expect(dateInputs).toHaveLength(2);
    expect((dateInputs[0] as HTMLInputElement).value).toBe('2025-03-01');
    expect((dateInputs[1] as HTMLInputElement).value).toBe('2025-03-14');
  });

  it('renders booking refs pre-filled', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const refsInput = container.querySelector(
      'input[autocomplete="off"]',
    ) as HTMLInputElement;
    expect(refsInput.value).toBe('TK123');
  });

  it('cancel link points back to the trip', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('a.btn-secondary')).toBeInTheDocument());

    const link = container.querySelector('a.btn-secondary') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('#/trips/trip-99');
  });

  it('calls tripsApi.update with edited name on submit', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    const nameInput = container.querySelector('input[type="text"][required]')!;
    await fireEvent.input(nameInput, { target: { value: 'Tokyo 2025 Updated' } });
    await fireEvent.submit(container.querySelector('form')!);

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(
        'trip-99',
        expect.objectContaining({ name: 'Tokyo 2025 Updated' }),
      );
    });
  });

  it('calls tripsApi.refreshImage after successful update', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);
    await waitFor(() => expect(mockRefreshImage).toHaveBeenCalledWith('trip-99'));
  });

  it('navigates back to trip detail on success', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/trips/trip-99'));
  });

  it('shows error message when update fails', async () => {
    mockUpdate.mockRejectedValue(new Error('Save failed'));
    const { container, findByText } = render(EditTripPage, {
      props: { params: { id: 'trip-99' } },
    });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    await fireEvent.submit(container.querySelector('form')!);
    expect(await findByText('Save failed')).toBeInTheDocument();
  });

  it('renders two airport comboboxes', async () => {
    const { container } = render(EditTripPage, { props: { params: { id: 'trip-99' } } });
    await waitFor(() => expect(container.querySelector('form')).toBeInTheDocument());

    expect(container.querySelectorAll('.airport-combobox')).toHaveLength(2);
  });
});
