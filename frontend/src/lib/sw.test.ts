/**
 * Tests for the service worker's fetch routing.
 *
 * `sw.js` runs in a worker global, so it is loaded here against a stubbed
 * `self` / `caches` and its registered `fetch` listener is driven directly.
 * That is worth the awkwardness for one reason: the bug this pins was invisible
 * in every other layer — saving a budget on a phone showed the old figure until
 * you navigated away and back, because the GET that followed the PUT beat the
 * cache purge and was served the pre-mutation copy.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
// Vite's `?raw` gives the worker's source as a string without needing node
// globals in a browser-environment test file.
import swSource from '../../sw.js?raw';

type FetchHandler = (event: FakeFetchEvent) => void;

interface FakeFetchEvent {
  request: Request;
  respondWith: (r: Response | Promise<Response>) => void;
  waitUntil: (p: Promise<unknown>) => void;
}

/** Records the order of cache deletes against network calls. */
let timeline: string[] = [];
let fetchHandler: FetchHandler;
let cacheEntries: Map<string, Response>;

function loadServiceWorker() {
  timeline = [];
  cacheEntries = new Map();

  const cache = {
    keys: async () => [...cacheEntries.keys()].map((url) => new Request(url)),
    delete: async (req: Request | string) => {
      timeline.push('purge');
      cacheEntries.delete(typeof req === 'string' ? req : req.url);
      return true;
    },
    match: async (req: Request) => cacheEntries.get(req.url),
    put: async (req: Request, res: Response) => {
      cacheEntries.set(req.url, res);
    },
  };

  const listeners: Record<string, FetchHandler> = {};
  const self = {
    addEventListener: (type: string, fn: FetchHandler) => {
      listeners[type] = fn;
    },
    location: { origin: 'https://partiu.test' },
    clients: { claim: () => {} },
    skipWaiting: () => {},
    caches: undefined as unknown,
  };

  const caches = {
    open: async () => cache,
    keys: async () => ['partiu-api-v21'],
    delete: async () => true,
    match: async (req: Request) => cacheEntries.get(req.url),
  };

  // `fetch` is forwarded rather than captured, so a stub installed after the
  // worker is loaded is still the one it calls.
  new Function('self', 'caches', 'fetch', swSource)(
    self,
    caches,
    (...args: [RequestInfo, RequestInit?]) => globalThis.fetch(...args),
  );

  fetchHandler = listeners.fetch;
  return { cache };
}

function dispatch(request: Request): Promise<Response> {
  let responded: Promise<Response> | null = null;
  fetchHandler({
    request,
    respondWith: (r) => {
      responded = Promise.resolve(r);
    },
    waitUntil: () => {},
  });
  if (!responded) throw new Error('the worker did not respond to this request');
  return responded;
}

describe('service worker API routing', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('purges the API cache before a mutation resolves, not after', async () => {
    loadServiceWorker();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        timeline.push('network');
        return new Response('{}', { status: 200 });
      }),
    );
    // Something in the cache to purge.
    cacheEntries.set('https://partiu.test/api/trips/t1/budget', new Response('{"amount":500}'));

    await dispatch(
      new Request('https://partiu.test/api/trips/t1/budget', { method: 'PUT' }),
    );

    /* The whole point: by the time the page sees the PUT resolve, the stale copy
     * is already gone. `waitUntil` made no such promise — it only keeps the
     * worker alive — so the re-read could win the race and serve the old value. */
    expect(timeline).toEqual(['network', 'purge']);
    expect(cacheEntries.size).toBe(0);
  });

  it('leaves the cache alone when the mutation fails', async () => {
    loadServiceWorker();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })));
    cacheEntries.set('https://partiu.test/api/trips/t1/budget', new Response('{"amount":500}'));

    await dispatch(new Request('https://partiu.test/api/trips/t1/budget', { method: 'PUT' }));

    // A rejected write changed nothing on the server; dropping the cache would
    // only cost a round trip.
    expect(cacheEntries.size).toBe(1);
  });

  it('does not handle cross-origin requests at all', () => {
    loadServiceWorker();
    let responded = false;
    fetchHandler({
      request: new Request('https://basemaps.cartocdn.com/tile.png'),
      respondWith: () => {
        responded = true;
      },
      waitUntil: () => {},
    });

    /* A dropped map tile must reach the page as a network error, not as this
     * worker's JSON 503 — that is what the basemap reads as "blocked". */
    expect(responded).toBe(false);
  });
});
