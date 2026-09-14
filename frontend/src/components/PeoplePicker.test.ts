import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import PeoplePicker from './PeoplePicker.svelte';
import type { Participant } from '../api/types';

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string, o?: { values?: Record<string, unknown> }) => string) => void) => {
      fn((k, o) => (o?.values ? `${k} ${Object.values(o.values).join(' ')}` : k));
      return () => {};
    },
  },
}));

const person = (id: number, name: string): Participant => ({ type: 'user', id, name });

/** A group trip's worth of companions — the case an inline list of everyone
 *  turns into a wall of names. */
const CROWD = [
  person(1, 'thiago'),
  person(2, 'barbara'),
  person(3, 'carlos'),
  person(4, 'ana'),
  person(5, 'joão'),
  person(6, 'maria'),
];

function setup(people: Participant[], selected = new Set<string>()) {
  const onToggle = vi.fn();
  const result = render(PeoplePicker, {
    props: { people, selected, onToggle, label: 'share with' },
  });
  const input = () => result.container.querySelector('.people-input') as HTMLInputElement;
  const rows = () => [...result.container.querySelectorAll('.people-suggestion')];
  return { ...result, onToggle, input, rows };
}

describe('PeoplePicker', () => {
  /* The whole point of a combobox here: at rest the control is what you have
   * chosen, not everyone who could be chosen. */
  it('shows no candidate list until you interact with it', () => {
    const { container } = setup(CROWD);
    expect(container.querySelector('.people-suggestions')).toBeNull();
  });

  it('shows what is already selected as tokens', () => {
    const { container } = setup(CROWD, new Set(['user:1', 'user:2']));
    const tokens = [...container.querySelectorAll('.people-token')].map((el) =>
      el.textContent?.replace('×', '').trim(),
    );
    expect(tokens).toEqual(['thiago', 'barbara']);
  });

  /* Type-to-search alone hides the fact that there is anything to pick, so
   * focusing opens the full list — the same rule `PlaceInput` follows. */
  it('opens the full list on focus, so it stays browsable', async () => {
    const { input, rows } = setup(CROWD);

    await fireEvent.focus(input());

    await waitFor(() => expect(rows()).toHaveLength(6));
  });

  it('narrows the suggestions as you type', async () => {
    const { input, rows } = setup(CROWD);
    await fireEvent.focus(input());

    await fireEvent.input(input(), { target: { value: 'car' } });

    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0].textContent).toContain('carlos');
  });

  /* The names here are typed by hand in a pt-BR app; a search that cannot find
   * its own users' names is worse than no search. */
  it('matches accented names typed without accents', async () => {
    const { input, rows } = setup(CROWD);
    await fireEvent.focus(input());

    await fireEvent.input(input(), { target: { value: 'joao' } });

    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0].textContent).toContain('joão');
  });

  it('is case insensitive', async () => {
    const { input, rows } = setup(CROWD);
    await fireEvent.focus(input());

    await fireEvent.input(input(), { target: { value: 'BARB' } });

    await waitFor(() => expect(rows()).toHaveLength(1));
  });

  it('adds someone when their suggestion is clicked', async () => {
    const { input, rows, onToggle } = setup(CROWD);
    await fireEvent.focus(input());
    await waitFor(() => expect(rows().length).toBeGreaterThan(0));

    await fireEvent.mouseDown(rows()[1]);

    expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ name: 'barbara' }));
  });

  it('clears the query after a pick, so the next name starts fresh', async () => {
    const { input, rows } = setup(CROWD);
    await fireEvent.focus(input());
    await fireEvent.input(input(), { target: { value: 'car' } });
    await waitFor(() => expect(rows()).toHaveLength(1));

    await fireEvent.mouseDown(rows()[0]);

    await waitFor(() => expect(input().value).toBe(''));
  });

  /* Someone already chosen is a token; leaving them in the list too offers one
   * person in two places — the bug the payer select had. */
  it('leaves people who are already chosen out of the suggestions', async () => {
    const { input, rows } = setup(CROWD, new Set(['user:1']));
    await fireEvent.focus(input());

    await waitFor(() => expect(rows()).toHaveLength(5));
    expect(rows().map((r) => r.textContent?.trim())).not.toContain('thiago');
  });

  it('says so when everyone has already been added', async () => {
    const { input, container } = setup([person(1, 'thiago')], new Set(['user:1']));
    await fireEvent.focus(input());

    await waitFor(() =>
      expect(container.querySelector('.people-empty')?.textContent).toContain('people.all_added'),
    );
  });

  it('says so when nothing matches what was typed', async () => {
    const { input, container } = setup(CROWD);
    await fireEvent.focus(input());

    await fireEvent.input(input(), { target: { value: 'zzzz' } });

    await waitFor(() =>
      expect(container.querySelector('.people-empty')?.textContent).toContain('people.no_matches'),
    );
  });

  it('removes someone through their token', async () => {
    const { container, onToggle } = setup(CROWD, new Set(['user:1']));

    await fireEvent.click(container.querySelector('.people-token-remove')!);

    expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ name: 'thiago' }));
  });

  describe('keyboard', () => {
    it('walks the list with the arrow keys and picks with Enter', async () => {
      const { input, rows, onToggle } = setup(CROWD);
      await fireEvent.focus(input());
      await waitFor(() => expect(rows().length).toBeGreaterThan(0));

      await fireEvent.keyDown(input(), { key: 'ArrowDown' });
      await fireEvent.keyDown(input(), { key: 'ArrowDown' });
      await fireEvent.keyDown(input(), { key: 'Enter' });

      expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ name: 'barbara' }));
    });

    it('picks the only match on Enter without arrowing to it first', async () => {
      const { input, rows, onToggle } = setup(CROWD);
      await fireEvent.focus(input());
      await fireEvent.input(input(), { target: { value: 'ana' } });
      await waitFor(() => expect(rows()).toHaveLength(1));

      await fireEvent.keyDown(input(), { key: 'Enter' });

      expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ name: 'ana' }));
    });

    /* Enter on an ambiguous query must not pick a name for you — and must not
     * submit the surrounding form either. */
    it('picks nobody on Enter when the query is ambiguous', async () => {
      const { input, onToggle } = setup(CROWD);
      await fireEvent.focus(input());
      await fireEvent.input(input(), { target: { value: 'a' } });

      await fireEvent.keyDown(input(), { key: 'Enter' });

      expect(onToggle).not.toHaveBeenCalled();
    });

    it('closes the list on Escape', async () => {
      const { input, container, rows } = setup(CROWD);
      await fireEvent.focus(input());
      await waitFor(() => expect(rows().length).toBeGreaterThan(0));

      await fireEvent.keyDown(input(), { key: 'Escape' });

      await waitFor(() => expect(container.querySelector('.people-suggestions')).toBeNull());
    });

    /* The standard token-field gesture. */
    it('takes back the last token on Backspace in an empty box', async () => {
      const { input, onToggle } = setup(CROWD, new Set(['user:1', 'user:2']));

      await fireEvent.keyDown(input(), { key: 'Backspace' });

      expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ name: 'barbara' }));
    });

    it('leaves the tokens alone when Backspace is editing actual text', async () => {
      const { input, onToggle } = setup(CROWD, new Set(['user:1']));
      await fireEvent.input(input(), { target: { value: 'car' } });

      await fireEvent.keyDown(input(), { key: 'Backspace' });

      expect(onToggle).not.toHaveBeenCalled();
    });
  });

  it('never mutates the selection it is given', async () => {
    const selected = new Set<string>();
    const { input, rows } = setup(CROWD, selected);
    await fireEvent.focus(input());
    await waitFor(() => expect(rows().length).toBeGreaterThan(0));

    await fireEvent.mouseDown(rows()[0]);

    expect(selected.size).toBe(0);
  });
});
