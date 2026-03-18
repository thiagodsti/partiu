/**
 * Service Worker for Partiu PWA.
 * Implements a cache-first strategy for static assets,
 * network-first for API calls.
 *
 * Note: Vite outputs hashed filenames (e.g. index-Bo8Xdg-k.js) so we
 * cannot pre-cache a fixed list. Instead we cache assets on first fetch.
 */

const CACHE_VERSION = 'v10';
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

  // Static assets: cache-first (caches on first fetch)
  event.respondWith(cacheFirst(event.request, STATIC_CACHE));
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
