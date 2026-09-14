import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import TripExpenses from './TripExpenses.svelte';
import { currentUser } from '../lib/authStore';

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

    // Everyone on the trip starts selected, which the picker shows as tokens.
    const tokens = container.querySelectorAll('.people-token');
    expect(tokens.length).toBe(2);

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

  /* You are already in the trip's participant list — the owner and every
   * accepted collaborator are — so a separate "Me" option on top of it offered
   * the same person twice under two names. */
  describe('the payer picker does not offer you twice', () => {
    beforeEach(() => {
      currentUser.set({ id: '1', username: 'me', is_admin: false, smtp_recipient_address: null });
    });

    it('has one option per person and no extra "Me"', async () => {
      const { container, getByText } = render(TripExpenses, { tripId: 't1' });
      await waitFor(() => getByText('+ expenses.add'));
      await fireEvent.click(getByText('+ expenses.add'));

      const options = container.querySelectorAll('#new-paid-by option');
      expect(options.length).toBe(2);
      expect([...options].map((o) => (o as HTMLOptionElement).value)).toEqual([
        'user:1',
        'user:2',
      ]);
    });

    it('marks your own row rather than renaming it', async () => {
      const { container, getByText } = render(TripExpenses, { tripId: 't1' });
      await waitFor(() => getByText('+ expenses.add'));
      await fireEvent.click(getByText('+ expenses.add'));

      const options = [...container.querySelectorAll('#new-paid-by option')];
      expect(options[0].textContent).toContain('expenses.you');
      expect(options[1].textContent?.trim()).toBe('spouse');
    });

    it('preselects you, and sends you explicitly', async () => {
      const { container, getByText } = render(TripExpenses, { tripId: 't1' });
      await waitFor(() => getByText('+ expenses.add'));
      await fireEvent.click(getByText('+ expenses.add'));

      const select = container.querySelector('#new-paid-by') as HTMLSelectElement;
      expect(select.value).toBe('user:1');

      await fireEvent.input(container.querySelector('.expense-input-desc')!, {
        target: { value: 'Taxi' },
      });
      await fireEvent.input(container.querySelector('.expense-input-amount')!, {
        target: { value: '40' },
      });
      await fireEvent.click(getByText('expenses.save'));

      await waitFor(() => expect(mockCreate).toHaveBeenCalled());
      expect(mockCreate.mock.calls[0][1].paid_by).toEqual({ type: 'user', id: 1 });
    });

    /* The fallback the "Me" option still exists for: with no list to pick
     * yourself out of, the payer is omitted and the backend defaults to the
     * creator, which is you. */
    it('falls back to the "Me" option when the list is unavailable', async () => {
      mockParticipants.mockResolvedValue([]);
      const { container, getByText } = render(TripExpenses, { tripId: 't1' });
      await waitFor(() => getByText('+ expenses.add'));
      await fireEvent.click(getByText('+ expenses.add'));

      const options = container.querySelectorAll('#new-paid-by option');
      expect(options.length).toBe(1);
      expect((options[0] as HTMLOptionElement).value).toBe('');
    });
  });

  it('still shows a newly added expense even if the balances refresh fails', async () => {
    mockList.mockResolvedValueOnce([]).mockResolvedValueOnce([EXPENSE]);
    mockBalances
      .mockResolvedValueOnce({ balances: {} })
      .mockRejectedValueOnce(new Error('network error'));
    const { container, getByText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const desc = container.querySelector('.expense-input-desc') as HTMLInputElement;
    const amount = container.querySelector('.expense-input-amount') as HTMLInputElement;
    await fireEvent.input(desc, { target: { value: 'Lunch' } });
    await fireEvent.input(amount, { target: { value: '100' } });
    await fireEvent.click(getByText('expenses.save'));

    await waitFor(() => expect(container.textContent).toContain('Lunch'));
  });

  it('unchecking a participant excludes them from the split', async () => {
    const { container, getByText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const desc = container.querySelector('.expense-input-desc') as HTMLInputElement;
    const amount = container.querySelector('.expense-input-amount') as HTMLInputElement;
    await fireEvent.input(desc, { target: { value: 'Taxi' } });
    await fireEvent.input(amount, { target: { value: '40' } });

    // Dropping someone from the split is removing their token.
    const remove = container.querySelectorAll('.people-token-remove');
    await fireEvent.click(remove[1]);

    await fireEvent.click(getByText('expenses.save'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const [, payload] = mockCreate.mock.calls[0];
    expect(payload.participants).toEqual([{ type: 'user', id: 1 }]);
  });

  it('does not submit when every participant is unchecked, even via Enter', async () => {
    const { container, getByText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const desc = container.querySelector('.expense-input-desc') as HTMLInputElement;
    const amount = container.querySelector('.expense-input-amount') as HTMLInputElement;
    await fireEvent.input(desc, { target: { value: 'Taxi' } });
    await fireEvent.input(amount, { target: { value: '40' } });

    // Removing every token leaves nobody to split between.
    await fireEvent.click(container.querySelectorAll('.people-token-remove')[1]);
    await fireEvent.click(container.querySelectorAll('.people-token-remove')[0]);

    const saveButton = getByText('expenses.save') as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);

    await fireEvent.keyDown(amount, { key: 'Enter' });

    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('quick-adding a guest creates it and checks it as a participant', async () => {
    const { container, getByText, getByPlaceholderText } = render(TripExpenses, { tripId: 't1' });
    await waitFor(() => getByText('+ expenses.add'));
    await fireEvent.click(getByText('+ expenses.add'));

    const guestInput = getByPlaceholderText('expenses.add_guest_placeholder') as HTMLInputElement;
    await fireEvent.input(guestInput, { target: { value: 'Grandma' } });
    await fireEvent.click(getByText('+ expenses.add_guest'));

    await waitFor(() => expect(mockGuestCreate).toHaveBeenCalledWith('Grandma'));
    // The new guest joins the split immediately, as a third token.
    await waitFor(() => {
      const tokens = container.querySelectorAll('.people-token');
      expect(tokens.length).toBe(3);
    });
    const names = [...container.querySelectorAll('.people-token')].map((el) =>
      el.textContent?.replace('×', '').trim(),
    );
    expect(names).toContain('Grandma');
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
    const names = [...container.querySelectorAll('.people-token')].map((el) =>
      el.textContent?.replace('×', '').trim(),
    );
    expect(names).toContain('Alex');

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
