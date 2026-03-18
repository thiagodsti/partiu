import { writable } from 'svelte/store';

type Theme = 'system' | 'dark' | 'light';

const STORAGE_KEY = 'theme';

function getStored(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'dark' || v === 'light') return v;
  } catch {}
  return 'system';
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', theme);
  }
}

// Apply immediately on module load (before first render) to avoid flash
apply(getStored());

export const theme = writable<Theme>(getStored());

theme.subscribe(value => {
  try { localStorage.setItem(STORAGE_KEY, value); } catch {}
  apply(value);
});
