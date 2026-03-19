import { writable } from 'svelte/store';

type Toast = { id: number; message: string; type: string };

function createToastStore() {
  const { subscribe, update } = writable<Toast[]>([]);
  let counter = 0;

  function show(message: string, type = 'info', duration = 3000) {
    const id = ++counter;
    update((toasts) => [...toasts, { id, message, type }]);
    setTimeout(() => {
      update((toasts) => toasts.filter((t) => t.id !== id));
    }, duration);
  }

  return { subscribe, show };
}

export const toasts = createToastStore();
