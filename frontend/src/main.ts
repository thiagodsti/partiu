import './app.css';
import 'leaflet/dist/leaflet.css';
import './lib/themeStore'; // apply saved theme before first render
import './lib/i18n';
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

document.getElementById('initial-loader')?.remove();
const app = mount(App, { target: document.getElementById('app')! });

export default app;
