/**
 * Dropping the service worker's cached API responses when the account changes.
 *
 * `sw.js` caches `GET /api/*` under one cache per install, with nothing in the
 * key to say whose data it holds — and a PWA install is shared by everyone who
 * signs in on that device. Left in place across a sign-in, the next user is
 * served the previous one's trips and stats from cache while the network copy
 * is still in flight: one account showed another's visited countries, which is
 * how this was found.
 *
 * Called on **both** sides of the change — after a successful sign-in and on
 * sign-out — because either can be the one that happens on a shared phone.
 *
 * The page can reach CacheStorage directly, so this needs no message plumbing
 * and works even when no service worker is controlling the page (a fresh
 * install, or a browser that never registered one).
 */
const API_CACHE_PREFIX = 'partiu-api-';

export async function purgeApiCache(): Promise<void> {
  if (typeof caches === 'undefined') return;
  try {
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => n.startsWith(API_CACHE_PREFIX)).map((n) => caches.delete(n)),
    );
  } catch {
    // Never block signing in or out on a cache that would not clear: the worst
    // case is a stale read that the background revalidation corrects.
  }
}
