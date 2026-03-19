/**
 * Service Worker for Partiu PWA.
 * Implements a cache-first strategy for static assets,
 * network-first for API calls.
 *
 * Note: Vite outputs hashed filenames (e.g. index-Bo8Xdg-k.js) so we
 * cannot pre-cache a fixed list. Instead we cache assets on first fetch.
 */

const CACHE_VERSION = 'v13';
const STATIC_CACHE = `partiu-static-${CACHE_VERSION}`;
const API_CACHE = `partiu-api-${CACHE_VERSION}`;

// ---- Install: skip waiting immediately ----
self.addEventListener('install', () => {
  self.skipWaiting();
});

// ---- Activate: clean up old caches ----
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== STATIC_CACHE && k !== API_CACHE)
            .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ---- Fetch: routing strategy ----
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API requests: network-first, fall back to cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request, API_CACHE));
    return;
  }

  // Hashed static assets (/assets/*): cache-first — filenames change on deploy
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }

  // HTML / navigation (index.html, sw.js, manifest.json, icons…): network-first
  // so the app shell is always fresh after a deploy and chunk hashes stay in sync
  event.respondWith(networkFirst(event.request, STATIC_CACHE));
});

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('<h1>Offline</h1>', {
      headers: { 'Content-Type': 'text/html' },
    });
  }
}

// ---- Push notifications ----
self.addEventListener('push', (event) => {
  console.log('[SW] push event received', event.data ? 'with data' : 'no data');
  if (!event.data) return;

  let payload = { title: 'Partiu', body: '', url: '/' };
  try {
    payload = { ...payload, ...event.data.json() };
  } catch {
    payload.body = event.data.text();
  }

  console.log('[SW] showing notification:', payload.title);
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/icon-192.png',
      data: { url: payload.url },
    }).then(() => {
      console.log('[SW] notification shown OK');
    }).catch((err) => {
      console.error('[SW] showNotification failed:', err);
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.postMessage({ type: 'navigate', url });
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});

async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'Offline' }), {
      headers: { 'Content-Type': 'application/json' },
      status: 503,
    });
  }
}
