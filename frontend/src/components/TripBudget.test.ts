import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import TripBudget from './TripBudget.svelte';

const { mockGet, mockSet, mockClear } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockSet: vi.fn(),
  mockClear: vi.fn(),
}));

vi.mock('../api/client', () => ({
  budgetApi: { get: mockGet, set: mockSet, clear: mockClear },
}));

vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (k: string) => string) => void) => { fn((k: string) => k); return () => {}; } },
}));

const props = { tripId: 'trip-1', defaultCurrency: 'EUR' };

function budget(spent: number, amount: number | null = 800, uncounted = {}) {
  return { amount, currency: amount === null ? null : 'EUR', spent, uncounted };
}

describe('TripBudget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSet.mockResolvedValue({ ok: true });
    mockClear.mockResolvedValue({ ok: true });
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

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith('trip-1', 800, 'EUR'));
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

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith('trip-1', 1200.5, 'EUR'));
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
  it('re-reads on demand when the expense list reports a change', async () => {
    mockGet.mockResolvedValue(budget(200));
    const { component } = render(TripBudget, { props });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    await (component as unknown as { reload: () => Promise<void> }).reload();

    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});
