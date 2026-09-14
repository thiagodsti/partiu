import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

const updateMe = vi.hoisted(() => vi.fn().mockResolvedValue({ ok: true }));
vi.mock('../api/client', () => ({ authApi: { updateMe } }));

/** Fresh module per test: the store paints the cached value at import time. */
async function load() {
  vi.resetModules();
  return import('./accentStore');
}

describe('accentStore', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-accent');
    updateMe.mockClear();
  });

  it('defaults to sky when nothing is cached', async () => {
    const { accent, DEFAULT_ACCENT } = await load();
    expect(DEFAULT_ACCENT).toBe('sky');
    expect(get(accent)).toBe('sky');
  });

  // The cache exists only to avoid a flash of the default colour while
  // /api/auth/me is in flight — it is never the source of truth.
  it('paints the cached value at import time, before anything renders', async () => {
    localStorage.setItem('accent', 'ocean');
    await load();
    expect(document.documentElement.getAttribute('data-accent')).toBe('ocean');
  });

  it('ignores a cached value that is not a known preset', async () => {
    localStorage.setItem('accent', 'chartreuse');
    const { accent } = await load();
    expect(get(accent)).toBe('sky');
    expect(document.documentElement.getAttribute('data-accent')).toBe('sky');
  });

  it('survives storage being unavailable', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    const { accent } = await load();
    expect(get(accent)).toBe('sky');
    getItem.mockRestore();
  });

  it('lists every preset the stylesheet defines, sky first', async () => {
    const { ACCENTS } = await load();
    expect(ACCENTS.map((a) => a.value)).toEqual(['sky', 'ocean', 'dusk', 'orchid', 'graphite']);
  });

  describe('setAccent', () => {
    it('persists the choice to the user account, not just the browser', async () => {
      const { setAccent } = await load();
      setAccent('dusk');
      expect(updateMe).toHaveBeenCalledWith({ accent: 'dusk' });
    });

    it('applies immediately rather than waiting for the server', async () => {
      updateMe.mockReturnValueOnce(new Promise(() => {})); // never resolves
      const { setAccent, accent } = await load();
      setAccent('orchid');
      expect(get(accent)).toBe('orchid');
      expect(document.documentElement.getAttribute('data-accent')).toBe('orchid');
    });

    it('keeps the chosen colour when the save fails', async () => {
      updateMe.mockRejectedValueOnce(new Error('offline'));
      const { setAccent, accent } = await load();
      setAccent('ocean');
      await Promise.resolve();
      expect(get(accent)).toBe('ocean');
    });
  });

  describe('applyUserAccent', () => {
    it("adopts the signed-in user's accent over whatever the browser cached", async () => {
      localStorage.setItem('accent', 'orchid');
      const { applyUserAccent, accent } = await load();
      applyUserAccent('ocean');
      expect(get(accent)).toBe('ocean');
      expect(document.documentElement.getAttribute('data-accent')).toBe('ocean');
    });

    // The server is telling the client here, not the reverse: echoing it back
    // would have the borrowed-browser case donate one user's colour to another.
    it('does not write back to the server', async () => {
      const { applyUserAccent } = await load();
      applyUserAccent('dusk');
      expect(updateMe).not.toHaveBeenCalled();
    });

    it('falls back to the default for a user row with no accent', async () => {
      localStorage.setItem('accent', 'dusk');
      const { applyUserAccent, accent } = await load();
      applyUserAccent(undefined);
      expect(get(accent)).toBe('sky');
    });
  });
});
