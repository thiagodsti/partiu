import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import TripBudget from './TripBudget.svelte';
import { currentUser } from '../lib/authStore';

const { mockGet, mockSet, mockClear, mockParticipants } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockSet: vi.fn(),
  mockClear: vi.fn(),
  mockParticipants: vi.fn(),
}));

vi.mock('../api/client', () => ({
  budgetApi: { get: mockGet, set: mockSet, clear: mockClear },
  // The edit form offers a "share with" row, so opening it reads the trip's
  // participant list. One name means there is nobody to share with and the row
  // does not render — which is what every test here but the sharing ones want.
  expensesApi: { participants: mockParticipants },
}));

/* The key stands in for the string, with any interpolated values appended —
 * several assertions here are about *which name* a sentence carries, and a mock
 * that dropped the values would pass whatever name the component printed. */
vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string, o?: { values?: Record<string, unknown> }) => string) => void) => {
      fn((k, o) => (o?.values ? `${k} ${Object.values(o.values).join(' ')}` : k));
      return () => {};
    },
  },
}));

const props = { tripId: 'trip-1', defaultCurrency: 'EUR' };

function budget(
  spent: number,
  amount: number | null = 800,
  uncounted = {},
  members: { type: 'user' | 'guest'; id: number; name: string }[] = [
    { type: 'user', id: 1, name: 'me' },
  ],
) {
  return {
    amount,
    currency: amount === null ? null : 'EUR',
    spent,
    uncounted,
    members,
    owner_user_id: 1,
    owner_username: 'me',
  };
}

describe('TripBudget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSet.mockResolvedValue({ ok: true });
    mockClear.mockResolvedValue({ ok: true });
    mockParticipants.mockResolvedValue([{ type: 'user', id: 1, name: 'me' }]);
  });

  /* Amber before the limit, red past it. Green is deliberately absent: it means
   * "done" everywhere else in this app, and being under budget on day two of a
   * trip is not a finished thing. */
  describe('colour states', () => {
    const levelOf = async (spent: number) => {
      mockGet.mockResolvedValue(budget(spent));
      const { container } = render(TripBudget, { props });
      await waitFor(() => expect(container.querySelector('.budget')).toBeInTheDocument());
      return container.querySelector('.budget')?.getAttribute('data-level');
    };

    it('is neutral well under the limit', async () => {
      expect(await levelOf(200)).toBe('under');
    });

    it('warns as the limit approaches', async () => {
      expect(await levelOf(640)).toBe('near'); // exactly 80%
      expect(await levelOf(799)).toBe('near');
    });

    it('is neutral just below the warning threshold', async () => {
      expect(await levelOf(639)).toBe('under');
    });

    it('goes red at the limit, not one euro past it', async () => {
      // Spending exactly your budget is spending all of it; a bar still amber
      // while the money is gone reads as "nearly there".
      expect(await levelOf(799)).toBe('near');
      expect(await levelOf(800)).toBe('over');
      expect(await levelOf(801)).toBe('over');
    });
  });

  /* Within a band the bar deepens as it fills: light green → strong green, then
   * light amber → strong amber, then light red → stronger. The band gives the
   * hue, `--budget-mix` gives its strength. */
  describe('intensity within a band', () => {
    const mixOf = async (spent: number) => {
      mockGet.mockResolvedValue(budget(spent));
      const { container } = render(TripBudget, { props });
      await waitFor(() => expect(container.querySelector('.budget')).toBeInTheDocument());
      const style = (container.querySelector('.budget') as HTMLElement).style;
      return Number(style.getPropertyValue('--budget-mix'));
    };

    it('deepens as the bar fills', async () => {
      expect(await mixOf(80)).toBeLessThan(await mixOf(400));
      expect(await mixOf(400)).toBeLessThan(await mixOf(630));
    });

    it('starts pale again on entering the next band', async () => {
      // 79% is the deepest green; 81% is the palest amber.
      expect(await mixOf(648)).toBeLessThan(await mixOf(632));
    });

    it('never mixes so far into the track that the bar disappears', async () => {
      expect(await mixOf(0)).toBeGreaterThanOrEqual(35);
    });

    it('tops out rather than deepening forever past the limit', async () => {
      // Well beyond the budget there is nothing a deeper red would add.
      expect(await mixOf(1040)).toBe(100);
      expect(await mixOf(5000)).toBe(100);
    });
  });

  it('says the budget is spent rather than "0 over" at exactly the limit', async () => {
    mockGet.mockResolvedValue(budget(800));
    const { container } = render(TripBudget, { props });

    await waitFor(() => expect(container.querySelector('.budget-note')).toBeInTheDocument());
    expect(container.querySelector('.budget-note')?.textContent).toContain('budget.reached');
  });

  it('stops the bar at the limit while the number keeps going', async () => {
    mockGet.mockResolvedValue(budget(1600)); // twice the budget
    const { container } = render(TripBudget, { props });

    await waitFor(() => expect(container.querySelector('.budget-fill')).toBeInTheDocument());
    expect((container.querySelector('.budget-fill') as HTMLElement).style.width).toBe('100%');
    expect(container.querySelector('.budget-note')?.textContent).toContain('budget.over_by');
  });

  // No exchange rates here: what falls outside the budget's currency is named,
  // never folded in.
  it('lists spend in other currencies without converting it', async () => {
    mockGet.mockResolvedValue(budget(420, 800, { SEK: 900, BRL: 240 }));
    const { container } = render(TripBudget, { props });

    await waitFor(() => expect(container.querySelector('.budget-uncounted')).toBeInTheDocument());
    const text = container.querySelector('.budget-uncounted')?.textContent ?? '';
    expect(text).toContain('BRL 240');
    expect(text).toContain('SEK 900');
  });

  it('offers to set one when the trip has no budget', async () => {
    mockGet.mockResolvedValue(budget(0, null));
    const { container } = render(TripBudget, { props });

    await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());
    expect(container.querySelector('.budget')).toBeNull();
  });

  it('saves a budget and re-reads the spend', async () => {
    mockGet.mockResolvedValue(budget(0, null));
    const { container } = render(TripBudget, { props });
    await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

    await fireEvent.click(container.querySelector('.budget-empty-row button')!);
    await fireEvent.input(container.querySelector('.budget-form input')!, {
      target: { value: '800' },
    });
    await fireEvent.click(container.querySelector('.budget-actions button')!);

    await waitFor(() =>
      expect(mockSet).toHaveBeenCalledWith('trip-1', 800, 'EUR', [{ type: 'user', id: 1 }]),
    );
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('accepts a comma decimal, which is what a pt-BR keyboard gives', async () => {
    mockGet.mockResolvedValue(budget(0, null));
    const { container } = render(TripBudget, { props });
    await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

    await fireEvent.click(container.querySelector('.budget-empty-row button')!);
    await fireEvent.input(container.querySelector('.budget-form input')!, {
      target: { value: '1200,50' },
    });
    await fireEvent.click(container.querySelector('.budget-actions button')!);

    await waitFor(() =>
      expect(mockSet).toHaveBeenCalledWith('trip-1', 1200.5, 'EUR', [{ type: 'user', id: 1 }]),
    );
  });

  it('refuses a budget of zero rather than sending it', async () => {
    mockGet.mockResolvedValue(budget(0, null));
    const { container } = render(TripBudget, { props });
    await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

    await fireEvent.click(container.querySelector('.budget-empty-row button')!);
    await fireEvent.input(container.querySelector('.budget-form input')!, {
      target: { value: '0' },
    });
    await fireEvent.click(container.querySelector('.budget-actions button')!);

    await waitFor(() => expect(container.querySelector('.budget-error')).toBeInTheDocument());
    expect(mockSet).not.toHaveBeenCalled();
  });

  /* `reload()` is a method rather than a `revision` prop on purpose: bumping a
   * counter from the expense list's `onchange` re-renders the trip page, which
   * hands the list a fresh callback, which re-runs its reporting effect, which
   * bumps the counter again. Every trip-page test timed out on that loop. */
  /* A budget can belong to more than one person. The figure then measures
   * their *combined* share, which is a different number from your own — so the
   * panel has to say whose money the bar is showing. */
  describe('sharing', () => {
    const them = { type: 'user' as const, id: 2, name: 'barbara' };
    const me = { type: 'user' as const, id: 1, name: 'thiago' };

    beforeEach(() => {
      currentUser.set({ id: '1', username: 'thiago', is_admin: false, smtp_recipient_address: null });
    });

    it('names who a shared budget is shared with', async () => {
      mockGet.mockResolvedValue(budget(300, 800, {}, [me, them]));
      const { container } = render(TripBudget, { props });

      await waitFor(() =>
        expect(container.querySelector('.budget-shared-line')?.textContent).toContain('barbara'),
      );
    });

    it('says nothing about sharing when the budget is yours alone', async () => {
      mockGet.mockResolvedValue(budget(300, 800, {}, [me]));
      const { container } = render(TripBudget, { props });

      await waitFor(() => expect(container.querySelector('.budget')).toBeInTheDocument());
      expect(container.querySelector('.budget-shared-line')).toBeNull();
    });

    /* A member may edit and clear a shared budget, so the panel names its
     * owner before offering either. */
    it("names the owner when the budget is someone else's", async () => {
      mockGet.mockResolvedValue({
        ...budget(300, 800, {}, [me, them]),
        owner_user_id: 2,
        owner_username: 'barbara',
      });
      const { container } = render(TripBudget, { props });

      await waitFor(() =>
        expect(container.querySelector('.budget-owner')?.textContent).toContain('barbara'),
      );
    });

    it('sends the chosen members when saving', async () => {
      mockGet.mockResolvedValue(budget(0, null, {}, [me]));
      mockParticipants.mockResolvedValue([me, them]);
      const { container } = render(TripBudget, { props });
      await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

      await fireEvent.click(container.querySelector('.budget-empty-row button')!);
      await waitFor(() => expect(container.querySelector('.people-input')).toBeInTheDocument());
      await fireEvent.input(container.querySelector('.budget-form input')!, {
        target: { value: '800' },
      });

      // Add the partner through the combobox: focus, then pick her suggestion.
      // You are already a token, so she is the only thing offered.
      await fireEvent.focus(container.querySelector('.people-input')!);
      await waitFor(() => expect(container.querySelectorAll('.people-suggestion')).toHaveLength(1));
      await fireEvent.mouseDown(container.querySelector('.people-suggestion')!);

      await fireEvent.click(container.querySelector('.budget-actions button')!);

      await waitFor(() =>
        expect(mockSet).toHaveBeenCalledWith('trip-1', 800, 'EUR', [
          { type: 'user', id: 1 },
          { type: 'user', id: 2 },
        ]),
      );
    });

    /* The number of people on a trip has no upper bound, which is why the
     * picker is a combobox: at rest it costs the form only the names you have
     * chosen, and the candidates live in an overlay. */
    it('stays compact on a crowded trip, with everyone still reachable', async () => {
      mockGet.mockResolvedValue(budget(0, null, {}, [me]));
      mockParticipants.mockResolvedValue([
        me,
        them,
        { type: 'user' as const, id: 3, name: 'carlos' },
        { type: 'user' as const, id: 4, name: 'ana' },
        { type: 'guest' as const, id: 5, name: 'joao' },
        { type: 'guest' as const, id: 6, name: 'maria' },
        { type: 'guest' as const, id: 7, name: 'pedro' },
      ]);
      const { container } = render(TripBudget, { props });
      await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

      await fireEvent.click(container.querySelector('.budget-empty-row button')!);
      await waitFor(() => expect(container.querySelector('.people-input')).toBeInTheDocument());

      // At rest the form shows one token (you) and no candidate list at all —
      // seven people cost it nothing.
      expect(container.querySelectorAll('.people-token')).toHaveLength(1);
      expect(container.querySelector('.people-suggestions')).toBeNull();

      // And everyone is still reachable by name, including the last of them.
      await fireEvent.focus(container.querySelector('.people-input')!);
      await fireEvent.input(container.querySelector('.people-input')!, {
        target: { value: 'pedro' },
      });
      await waitFor(() => expect(container.querySelectorAll('.people-suggestion')).toHaveLength(1));
      expect(container.querySelector('.people-suggestion')?.textContent).toContain('pedro');
    });

    /* Nobody to share with is the common case, and an empty row of one chip
     * asking who to share with is a question with one answer. */
    it('hides the sharing row on a trip with only you on it', async () => {
      mockGet.mockResolvedValue(budget(0, null, {}, [me]));
      mockParticipants.mockResolvedValue([me]);
      const { container } = render(TripBudget, { props });
      await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

      await fireEvent.click(container.querySelector('.budget-empty-row button')!);
      await waitFor(() => expect(container.querySelector('.budget-form')).toBeInTheDocument());
      expect(container.querySelector('.budget-share')).toBeNull();
    });

    /* Choosing who shares is secondary to setting an amount, so a geocoder-
     * style failure must not take the form down with it. */
    it('still lets you set an amount when the participant list fails', async () => {
      mockGet.mockResolvedValue(budget(0, null, {}, [me]));
      mockParticipants.mockRejectedValue(new Error('offline'));
      const { container } = render(TripBudget, { props });
      await waitFor(() => expect(container.querySelector('.budget-empty-row')).toBeInTheDocument());

      await fireEvent.click(container.querySelector('.budget-empty-row button')!);
      await waitFor(() => expect(container.querySelector('.budget-form')).toBeInTheDocument());
      await fireEvent.input(container.querySelector('.budget-form input')!, {
        target: { value: '800' },
      });
      await fireEvent.click(container.querySelector('.budget-actions button')!);

      await waitFor(() => expect(mockSet).toHaveBeenCalled());
    });
  });

  it('re-reads on demand when the expense list reports a change', async () => {
    mockGet.mockResolvedValue(budget(200));
    const { component } = render(TripBudget, { props });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    await (component as unknown as { reload: () => Promise<void> }).reload();

    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});
