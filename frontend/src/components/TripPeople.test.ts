import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import TripPeople from './TripPeople.svelte';

const { mockListForTrip, mockList, mockAddToTrip, mockRemoveFromTrip, mockCreate } = vi.hoisted(
  () => ({
    mockListForTrip: vi.fn(),
    mockList: vi.fn(),
    mockAddToTrip: vi.fn(),
    mockRemoveFromTrip: vi.fn(),
    mockCreate: vi.fn(),
  }),
);

vi.mock('../api/client', () => ({
  guestsApi: {
    listForTrip: mockListForTrip,
    list: mockList,
    addToTrip: mockAddToTrip,
    removeFromTrip: mockRemoveFromTrip,
    create: mockCreate,
  },
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (key: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

vi.mock('../lib/authStore', () => ({
  currentUser: {
    subscribe: (fn: (v: { username: string }) => void) => {
      fn({ username: 'thiago' });
      return () => {};
    },
  },
}));

const TRIP = { id: 'trip-1', name: 'Sardinia' } as never;

describe('TripPeople', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListForTrip.mockResolvedValue([]);
    mockList.mockResolvedValue([]);
  });

  it('always lists the owner, so a solo trip is not an empty card', async () => {
    render(TripPeople, { props: { trip: TRIP } });
    await waitFor(() => expect(screen.getByText('thiago')).toBeTruthy());
  });

  it("shows the trip's guests, not the whole address book", async () => {
    // The scoping the per-trip roster exists for: Lucas is in your contacts but
    // not on this trip, so he is offered as an *addition*, never as a member.
    mockListForTrip.mockResolvedValue([{ id: 1, name: 'Jimmy', owner_id: 1, created_at: '' }]);
    mockList.mockResolvedValue([
      { id: 1, name: 'Jimmy', owner_id: 1, created_at: '' },
      { id: 2, name: 'Lucas', owner_id: 1, created_at: '' },
    ]);

    render(TripPeople, { props: { trip: TRIP } });

    await waitFor(() => expect(screen.getByText('Jimmy')).toBeTruthy());
    expect(screen.getByText('+ Lucas')).toBeTruthy();
  });

  it('adds someone from the address book to this trip', async () => {
    mockList.mockResolvedValue([{ id: 2, name: 'Lucas', owner_id: 1, created_at: '' }]);
    mockAddToTrip.mockResolvedValue({ id: 2, name: 'Lucas' });

    render(TripPeople, { props: { trip: TRIP } });
    await waitFor(() => expect(screen.getByText('+ Lucas')).toBeTruthy());

    await fireEvent.click(screen.getByText('+ Lucas'));
    expect(mockAddToTrip).toHaveBeenCalledWith('trip-1', 2);
  });

  it('creates a brand-new guest and puts them on the trip in one go', async () => {
    mockCreate.mockResolvedValue({ id: 7, ok: true });
    mockAddToTrip.mockResolvedValue({ id: 7, name: 'Vivian' });

    render(TripPeople, { props: { trip: TRIP } });
    await waitFor(() => expect(screen.getByText('thiago')).toBeTruthy());

    const input = screen.getByPlaceholderText('trip_people.add_placeholder');
    await fireEvent.input(input, { target: { value: 'Vivian' } });
    await fireEvent.click(screen.getByText('trip_people.add'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledWith('Vivian'));
    expect(mockAddToTrip).toHaveBeenCalledWith('trip-1', 7);
  });

  it('explains a refused removal instead of showing the raw error', async () => {
    // The backend answers 409 when an expense on the trip still names them.
    mockListForTrip.mockResolvedValue([{ id: 1, name: 'Jimmy', owner_id: 1, created_at: '' }]);
    mockRemoveFromTrip.mockRejectedValue(new Error('HTTP 409'));

    render(TripPeople, { props: { trip: TRIP } });
    await waitFor(() => expect(screen.getByText('Jimmy')).toBeTruthy());

    await fireEvent.click(screen.getByLabelText('trip_people.remove'));
    await waitFor(() => expect(screen.getByText('trip_people.remove_blocked')).toBeTruthy());
  });

  it('renders the trip even when the address book fails to load', async () => {
    // Your contacts are a convenience; the roster is the point.
    mockListForTrip.mockResolvedValue([{ id: 1, name: 'Jimmy', owner_id: 1, created_at: '' }]);
    mockList.mockRejectedValue(new Error('offline'));

    render(TripPeople, { props: { trip: TRIP } });
    await waitFor(() => expect(screen.getByText('Jimmy')).toBeTruthy());
  });

  it('reports the roster upward so the header count stays live', async () => {
    mockListForTrip.mockResolvedValue([
      { id: 1, name: 'Jimmy', owner_id: 1, created_at: '' },
      { id: 2, name: 'Lucas', owner_id: 1, created_at: '' },
    ]);
    const onchange = vi.fn();

    render(TripPeople, { props: { trip: TRIP, onchange } });
    await waitFor(() => expect(onchange).toHaveBeenCalled());
    expect(onchange.mock.lastCall?.[0]).toHaveLength(2);
  });

  it('shows collaborators and outstanding invitations apart from guests', async () => {
    render(TripPeople, {
      props: {
        trip: TRIP,
        collaborators: [
          { user_id: 2, username: 'barbara', status: 'accepted' },
          { user_id: 3, username: 'ana', status: 'pending' },
        ] as never,
      },
    });

    await waitFor(() => expect(screen.getByText('barbara')).toBeTruthy());
    expect(screen.getByText('trip_people.collaborator')).toBeTruthy();
    expect(screen.getByText('ana')).toBeTruthy();
    expect(screen.getByText('trip_people.invited')).toBeTruthy();
  });
});
