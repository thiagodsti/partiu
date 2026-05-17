/**
 * Service Worker for Partiu PWA.
 *
 * Strategies:
 *   - GET /api/auth/*      → network-first (session state must always be fresh)
 *   - GET /api/*           → stale-while-revalidate (serve cache instantly, update in background)
 *   - non-GET /api/*       → pass-through (mutations never cached)
 *   - /assets/*            → cache-first (content-hashed filenames)
 *   - everything else      → network-first (app shell, always get latest deploy)
 */

const CACHE_VERSION = 'v15';
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

  if (url.pathname.startsWith('/api/')) {
    // Only cache GET requests; mutations pass through unchanged
    if (event.request.method !== 'GET') return;

    // Auth endpoints are always network-first so session state is never stale
    if (url.pathname.startsWith('/api/auth/')) {
      event.respondWith(networkFirst(event.request, API_CACHE));
      return;
    }

    // All other GET API calls: serve stale immediately, revalidate in background
    event.respondWith(staleWhileRevalidate(event.request, API_CACHE));
    return;
  }

  // Hashed static assets (/assets/*): cache-first — filenames change on deploy
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }

  // HTML / navigation: network-first so the app shell is always fresh after a deploy
  event.respondWith(networkFirst(event.request, STATIC_CACHE));
});

// ---- Strategies ----

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

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  // Always kick off a background network fetch to keep the cache warm
  const networkFetch = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);

  // Return stale immediately if available; background fetch will update the cache
  if (cached) return cached;

  // No cached copy — must wait for the network
  const response = await networkFetch;
  if (response) return response;
  return new Response(JSON.stringify({ error: 'Offline' }), {
    headers: { 'Content-Type': 'application/json' },
    status: 503,
  });
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
  const badgeCount = typeof payload.badge === 'number' ? payload.badge : undefined;
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/icon-192.png',
      data: { url: payload.url },
    }).then(() => {
      console.log('[SW] notification shown OK');
      if (badgeCount !== undefined && 'setAppBadge' in self.registration) {
        return self.registration.setAppBadge(badgeCount);
      }
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
