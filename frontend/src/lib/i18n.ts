import { init, register, locale, _ } from 'svelte-i18n';
import { authApi } from '../api/client';

const STORAGE_KEY = 'locale';

const VALID_LOCALES = new Set(['en', 'pt-BR']);

export function getStoredLocale(): string {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v && VALID_LOCALES.has(v)) return v;
  } catch {}
  return 'en';
}

register('en', () => import('../locales/en.json'));
register('pt-BR', () => import('../locales/pt-BR.json'));

init({
  fallbackLocale: 'en',
  initialLocale: getStoredLocale(),
});

export { locale, _ as t };

export const LOCALES: { value: string; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'pt-BR', label: 'Português (BR)' },
];

/** Apply a locale received from the server (no API call). */
export function applyUserLocale(l: string | null | undefined) {
  const valid = l && VALID_LOCALES.has(l) ? l : 'en';
  try { localStorage.setItem(STORAGE_KEY, valid); } catch {}
  locale.set(valid);
}

/** Set locale locally and persist to the server. */
export function setLocale(l: string) {
  try { localStorage.setItem(STORAGE_KEY, l); } catch {}
  locale.set(l);
  authApi.updateMe({ locale: l }).catch(() => {});
}
