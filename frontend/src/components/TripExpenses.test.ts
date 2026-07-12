import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import TripExpenses from './TripExpenses.svelte';

const {
  mockList,
  mockCreate,
  mockUpdate,
  mockDelete,
  mockParticipants,
  mockBalances,
  mockGuestCreate,
  mockGuestList,
} = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
  mockUpdate: vi.fn(),
  mockDelete: vi.fn(),
  mockParticipants: vi.fn(),
  mockBalances: vi.fn(),
  mockGuestCreate: vi.fn(),
  mockGuestList: vi.fn(),
}));

vi.mock('../api/client', () => ({
  expensesApi: {
    list: mockList,
    create: mockCreate,
    update: mockUpdate,
    delete: mockDelete,
    participants: mockParticipants,
    balances: mockBalances,
  },
  guestsApi: {
    list: mockGuestList,
    create: mockGuestCreate,
    delete: vi.fn(),
  },
}));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string, o?: { values?: Record<string, unknown> }) => string) => void) => {
      fn((k: string, o?: { values?: Record<string, unknown> }) => {
        if (!o?.values) return k;
        return `${k} ${JSON.stringify(o.values)}`;
      });
      return () => {};
    },
  },
}));

vi.mock('svelte-i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

const EXPENSE = {
  id: 'e1',
  trip_id: 't1',
  description: 'Lunch',
  amount: 100,
  currency: 'EUR',
  created_by: 1,
  created_by_username: 'me',
  paid_by: { type: 'user' as const, id: 1, name: 'me' },
  participants: [
    { type: 'user' as const, id: 1, name: 'me' },
    { type: 'user' as const, id: 2, name: 'spouse' },
  ],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const PARTICIPANTS = [
  { type: 'user' as const, id: 1, name: 'me' },
  { type: 'user' as const, id: 2, name: 'spouse' },
];

describe('TripExpenses', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([]);
    mockParticipants.mockResolvedValue(PARTICIPANTS);
    mockBalances.mockResolvedValue({ balances: {} });
    mockCreate.mockResolvedValue({ id: 'new-id', ok: true });
    mockUpdate.mockResolvedValue({ ok: true });
    mockDelete.mockResolvedValue(null);
    mockGuestCreate.mockResolvedValue({ id: 99, ok: true });
    mockGuestList.mockResolvedValue([]);
  });

  it('shows empty state when there are no expenses', async () => {
    const { container } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => expect(container.textContent).toContain('expenses.empty'));
  });

  it('renders expense with paid-by and split info', async () => {
    mockList.mockResolvedValue([EXPENSE]);
    const { container } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => expect(container.textContent).toContain('Lunch'));
    expect(container.textContent).toContain('"name":"me"');
    expect(container.textContent).toContain('"n":2');
  });

  it('defaults the add form to paying for self and splitting between everyone', async () => {
    const { container, getByText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));

    await fireEvent.click(getByText('+ expenses.add'));

    const desc = container.querySelector('.expense-input-desc') as HTMLInputElement;
    const amount = container.querySelector('.expense-input-amount') as HTMLInputElement;
    await fireEvent.input(desc, { target: { value: 'Taxi' } });
    await fireEvent.input(amount, { target: { value: '40' } });

    const chips = container.querySelectorAll('.expense-participant-chip');
    expect(chips.length).toBe(2);
    chips.forEach((chip) => expect(chip.getAttribute('aria-pressed')).toBe('true'));

    await fireEvent.click(getByText('expenses.save'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const [, payload] = mockCreate.mock.calls[0];
    expect(payload.description).toBe('Taxi');
    expect(payload.amount).toBe(40);
    expect(payload.paid_by).toBeUndefined();
    expect(payload.participants).toEqual([
      { type: 'user', id: 1 },
      { type: 'user', id: 2 },
    ]);
  });

  it('unchecking a participant excludes them from the split', async () => {
    const { container, getByText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const desc = container.querySelector('.expense-input-desc') as HTMLInputElement;
    const amount = container.querySelector('.expense-input-amount') as HTMLInputElement;
    await fireEvent.input(desc, { target: { value: 'Taxi' } });
    await fireEvent.input(amount, { target: { value: '40' } });

    const chips = container.querySelectorAll('.expense-participant-chip');
    await fireEvent.click(chips[1]);

    await fireEvent.click(getByText('expenses.save'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const [, payload] = mockCreate.mock.calls[0];
    expect(payload.participants).toEqual([{ type: 'user', id: 1 }]);
  });

  it('quick-adding a guest creates it and checks it as a participant', async () => {
    const { container, getByText, getByPlaceholderText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const guestInput = getByPlaceholderText('expenses.add_guest_placeholder') as HTMLInputElement;
    await fireEvent.input(guestInput, { target: { value: 'Grandma' } });
    await fireEvent.click(getByText('+ expenses.add_guest'));

    await waitFor(() => expect(mockGuestCreate).toHaveBeenCalledWith('Grandma'));
    await waitFor(() => {
      const chips = container.querySelectorAll('.expense-participant-chip');
      expect(chips.length).toBe(3);
    });
    const guestChips = Array.from(container.querySelectorAll('.expense-participant-chip'));
    const guestChip = guestChips.find((c) => c.textContent?.includes('Grandma'));
    expect(guestChip?.getAttribute('aria-pressed')).toBe('true');
  });

  it('typing a name matching a guest from another trip offers it as a reuse suggestion', async () => {
    mockGuestList.mockResolvedValue([{ id: 5, name: 'Alex', created_at: '2026-01-01T00:00:00Z' }]);
    const { getByText, getByPlaceholderText, container } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const guestInput = getByPlaceholderText('expenses.add_guest_placeholder') as HTMLInputElement;
    await fireEvent.input(guestInput, { target: { value: 'Al' } });

    await waitFor(() => expect(container.textContent).toContain('Alex'));
    expect(container.querySelectorAll('.guest-suggestion-chip').length).toBe(1);

    await fireEvent.click(getByText('Alex'));

    // Reusing an existing guest must not create a new one.
    expect(mockGuestCreate).not.toHaveBeenCalled();
    const chips = Array.from(container.querySelectorAll('.expense-participant-chip'));
    const alexChip = chips.find((c) => c.textContent?.includes('Alex'));
    expect(alexChip?.getAttribute('aria-pressed')).toBe('true');

    const desc = container.querySelector('.expense-input-desc') as HTMLInputElement;
    const amount = container.querySelector('.expense-input-amount') as HTMLInputElement;
    await fireEvent.input(desc, { target: { value: 'Taxi' } });
    await fireEvent.input(amount, { target: { value: '40' } });

    await fireEvent.click(getByText('expenses.save'));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const [, payload] = mockCreate.mock.calls[0];
    expect(payload.participants).toEqual(
      expect.arrayContaining([{ type: 'guest', id: 5 }])
    );
  });

  it('deletes an expense after confirmation', async () => {
    mockList.mockResolvedValue([EXPENSE]);
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
    const { getByText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('Lunch'));

    await fireEvent.click(getByText('expenses.delete'));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('t1', 'e1'));
  });

  it('shows per-currency balances when toggled', async () => {
    mockBalances.mockResolvedValue({
      balances: {
        EUR: [
          { type: 'user', id: 1, name: 'me', net: 75 },
          { type: 'user', id: 2, name: 'spouse', net: -25 },
        ],
      },
    });
    const { getByText, container } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('expenses.balances_show'));

    await fireEvent.click(getByText('expenses.balances_show'));

    await waitFor(() => expect(container.textContent).toContain('+75'));
    expect(container.textContent).toContain('-25');
  });

  it('selecting a person to combine in one currency does not select them in another', async () => {
    mockBalances.mockResolvedValue({
      balances: {
        EUR: [{ type: 'user', id: 1, name: 'me', net: 75 }],
        BRL: [{ type: 'user', id: 1, name: 'me', net: 40 }],
      },
    });
    const { getByText, container } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('expenses.balances_show'));
    await fireEvent.click(getByText('expenses.balances_show'));
    await waitFor(() => expect(container.textContent).toContain('+75'));

    const rows = Array.from(container.querySelectorAll('.balance-row'));
    expect(rows.length).toBe(2);
    await fireEvent.click(rows[0]);

    expect(rows[0].getAttribute('aria-pressed')).toBe('true');
    expect(rows[1].getAttribute('aria-pressed')).toBe('false');
    expect(container.textContent).toContain('expenses.combined_total');
    // Only the EUR group should show a combined total; BRL has no selection.
    const combinedNodes = container.querySelectorAll('.balance-combined');
    expect(combinedNodes.length).toBe(1);
  });
});
