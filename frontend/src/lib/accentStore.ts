import { writable } from 'svelte/store';
import { authApi } from '../api/client';

/**
 * The interface wears one hue, and the reader picks it.
 *
 * The choice belongs to the **user**, not the browser: it is persisted on the
 * user row (`PATCH /api/auth/me`) and comes back on `/api/auth/me`, so the app
 * looks the same on a phone and a laptop and two people sharing a browser do
 * not overwrite each other. localStorage is kept as a *cache* of the last
 * known value, purely so the page can paint the right colour on load instead
 * of flashing the default blue for the length of the auth round-trip.
 *
 * The light/dark theme deliberately stays local-only (see themeStore): wanting
 * dark on a phone at night and light on a desktop is a real preference, and it
 * is about the device's surroundings rather than about the person.
 */
export type Accent = 'sky' | 'ocean' | 'dusk' | 'orchid' | 'graphite';

/** The order they appear in Settings. `label` is a locale key. */
export const ACCENTS: { value: Accent; label: string }[] = [
  { value: 'sky', label: 'settings.accent_sky' },
  { value: 'ocean', label: 'settings.accent_ocean' },
  { value: 'dusk', label: 'settings.accent_dusk' },
  { value: 'orchid', label: 'settings.accent_orchid' },
  { value: 'graphite', label: 'settings.accent_graphite' },
];

export const DEFAULT_ACCENT: Accent = 'sky';

const CACHE_KEY = 'accent';
const VALID = new Set<string>(ACCENTS.map((a) => a.value));

function normalize(value: string | null | undefined): Accent {
  return value && VALID.has(value) ? (value as Accent) : DEFAULT_ACCENT;
}

/** Last known value, used only to paint before the server answers. */
export function getCachedAccent(): Accent {
  try {
    return normalize(localStorage.getItem(CACHE_KEY));
  } catch {
    // private mode, storage disabled — the server value still arrives shortly
    return DEFAULT_ACCENT;
  }
}

function apply(accent: Accent) {
  document.documentElement.setAttribute('data-accent', accent);
  try { localStorage.setItem(CACHE_KEY, accent); } catch {}
}

// Applied on module load, before the first render, for the same reason the
// theme is: the alternative is a visible repaint on every cold start.
apply(getCachedAccent());

export const accent = writable<Accent>(getCachedAccent());

accent.subscribe(apply);

/**
 * Adopt the accent the server reports for the signed-in user, called from the
 * `/api/auth/me` handler alongside `applyUserLocale`. Writes nothing back —
 * this is the server telling the client, not the other way around, so a user
 * signing in on a borrowed browser gets their own colour rather than donating
 * the cached one to whoever was here before.
 */
export function applyUserAccent(value: string | null | undefined) {
  accent.set(normalize(value));
}

/** Set the accent locally and persist it to the user's account. */
export function setAccent(value: Accent) {
  accent.set(value);
  authApi.updateMe({ accent: value }).catch(() => {});
}
