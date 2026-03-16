import './app.css';
import App from './App.svelte';
import { mount } from 'svelte';

// Service Worker Registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => console.log('[SW] Registered:', reg.scope))
      .catch((err) => console.warn('[SW] Registration failed:', err));
  });
}

const app = mount(App, { target: document.getElementById('app')! });

export default app;
