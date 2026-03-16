/**
 * Partiu — SPA Shell
 * Simple hash-based router. Renders pages into #app.
 */

import TripsListPage from './pages/trips-list.js';
import TripDetailPage from './pages/trip-detail.js';
import FlightDetailPage from './pages/flight-detail.js';
import SettingsPage from './pages/settings.js';

// ---- Service Worker Registration ----
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => console.log('[SW] Registered:', reg.scope))
      .catch((err) => console.warn('[SW] Registration failed:', err));
  });
}

// ---- Router ----

const routes = [
  { pattern: /^\/trips\/([^/]+)\/flights\/([^/]+)$/, page: FlightDetailPage },
  { pattern: /^\/trips\/([^/]+)$/, page: TripDetailPage },
  { pattern: /^\/settings$/, page: SettingsPage },
  { pattern: /^\/$/, page: TripsListPage },
  { pattern: /^\/trips$/, page: TripsListPage },
];

let currentPage = null;

function getPath() {
  const hash = window.location.hash;
  if (!hash || hash === '#') return '/';
  return hash.slice(1); // Remove leading '#'
}

async function navigate(path) {
  if (!path.startsWith('/')) path = '/' + path;

  for (const route of routes) {
    const match = route.pattern.exec(path);
    if (match) {
      const params = match.slice(1);

      // Cleanup previous page
      if (currentPage && typeof currentPage.unmount === 'function') {
        currentPage.unmount();
      }

      const app = document.getElementById('app');
      app.innerHTML = '';

      try {
        currentPage = new route.page(app, ...params);
        await currentPage.mount();
      } catch (err) {
        console.error('Page error:', err);
        app.innerHTML = `
          <div class="main-content">
            <div class="empty-state">
              <div class="empty-state-icon">⚠️</div>
              <div class="empty-state-title">Something went wrong</div>
              <div class="empty-state-desc">${err.message}</div>
              <a href="#/trips" class="btn btn-primary">Go Home</a>
            </div>
          </div>
        `;
      }
      return;
    }
  }

  // 404
  document.getElementById('app').innerHTML = `
    <div class="main-content">
      <div class="empty-state">
        <div class="empty-state-icon">🔍</div>
        <div class="empty-state-title">Page not found</div>
        <div class="empty-state-desc">The page "${path}" doesn't exist.</div>
        <a href="#/trips" class="btn btn-primary">Go Home</a>
      </div>
    </div>
  `;
}

// ---- Navigation helpers ----

export function goTo(path) {
  window.location.hash = path;
}

export function showToast(message, type = 'info', duration = 3000) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ---- Tab Bar ----

function renderTabBar() {
  const existing = document.querySelector('.tab-bar');
  if (existing) return;

  const bar = document.createElement('nav');
  bar.className = 'tab-bar';
  bar.innerHTML = `
    <a class="tab-item" data-path="/trips" href="#/trips">
      <span class="tab-icon">✈</span>
      <span>Trips</span>
    </a>
    <a class="tab-item" data-path="/settings" href="#/settings">
      <span class="tab-icon">⚙</span>
      <span>Settings</span>
    </a>
  `;
  document.body.appendChild(bar);
}

function updateTabBar(path) {
  document.querySelectorAll('.tab-item').forEach((item) => {
    const itemPath = item.dataset.path;
    item.classList.toggle('active', path.startsWith(itemPath));
  });
}

// ---- Hash change handler ----

window.addEventListener('hashchange', () => {
  const path = getPath();
  navigate(path);
  updateTabBar(path);
});

// ---- Init ----

renderTabBar();
const initialPath = getPath();
navigate(initialPath);
updateTabBar(initialPath);
