import { init, register, locale, _ } from 'svelte-i18n';

const STORAGE_KEY = 'locale';

export function getStoredLocale(): string {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'en' || v === 'pt-BR') return v;
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

export function setLocale(l: string) {
  try { localStorage.setItem(STORAGE_KEY, l); } catch {}
  locale.set(l);
}
