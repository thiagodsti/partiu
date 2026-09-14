import './app.css';
import './lib/themeStore'; // apply saved theme before first render
// Imported here, not only from Settings: Settings is lazy-loaded, so a reader
// who chose a non-default accent would otherwise see the default one on every
// page until they happened to open Settings again.
import './lib/accentStore';
import './lib/i18n';
import App from './App.svelte';
import { mount } from 'svelte';

// Service Worker Registration
if ('serviceWorker' in navigator) {
  // Reload once a new service worker takes control, so the tab picks up the
  // new JS/CSS bundle instead of continuing to run the old one from memory.
  let reloadingForUpdate = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloadingForUpdate) return;
    reloadingForUpdate = true;
    window.location.reload();
  });

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => {
        console.log('[SW] Registered:', reg.scope);
        // A backgrounded PWA reopened from the home screen often resumes its
        // existing page instead of doing a fresh navigation, so the browser's
        // own update check never fires. Force one whenever the app regains
        // focus/visibility to catch new deploys promptly.
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') reg.update();
        });
        window.addEventListener('focus', () => reg.update());
      })
      .catch((err) => console.warn('[SW] Registration failed:', err));
  });
}

document.getElementById('initial-loader')?.remove();
const app = mount(App, { target: document.getElementById('app')! });

export default app;
