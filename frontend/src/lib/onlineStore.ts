import { readable } from 'svelte/store';

export const isOnline = readable(navigator.onLine, (set) => {
  const handleOnline = () => set(true);
  const handleOffline = () => set(false);
  window.addEventListener('online', handleOnline);
  window.addEventListener('offline', handleOffline);
  return () => {
    window.removeEventListener('online', handleOnline);
    window.removeEventListener('offline', handleOffline);
  };
});
