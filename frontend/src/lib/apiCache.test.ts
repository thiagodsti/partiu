import { describe, it, expect, vi, afterEach } from 'vitest';
import { purgeApiCache } from './apiCache';

/**
 * The bug behind this: `sw.js` caches `GET /api/*` under one cache per install,
 * with nothing in the key to say whose data it holds — and a PWA install is
 * shared by everyone who signs in on that device. One account was shown
 * another's visited countries, served from cache while the network copy was
 * still in flight.
 */
function stubCaches(names: string[]) {
  const deleted: string[] = [];
  vi.stubGlobal('caches', {
    keys: async () => names,
    delete: async (name: string) => {
      deleted.push(name);
      return true;
    },
  });
  return deleted;
}

describe('purgeApiCache', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('drops every versioned API cache', () => {
    const deleted = stubCaches(['partiu-api-v20', 'partiu-api-v21']);

    return purgeApiCache().then(() => {
      // Old versions too: an install that has not activated the new worker yet
      // still holds the previous account's answers.
      expect(deleted.sort()).toEqual(['partiu-api-v20', 'partiu-api-v21']);
    });
  });

  it('leaves the static caches alone', async () => {
    const deleted = stubCaches(['partiu-api-v21', 'partiu-static-v21', 'other-app-cache']);

    await purgeApiCache();

    // The app shell and its assets are the same for everyone; re-downloading
    // them on every sign-in would cost a cold start for no privacy gained.
    expect(deleted).toEqual(['partiu-api-v21']);
  });

  it('does nothing where CacheStorage is unavailable', async () => {
    vi.stubGlobal('caches', undefined);
    await expect(purgeApiCache()).resolves.toBeUndefined();
  });

  it('never rejects, so it cannot block signing in or out', async () => {
    vi.stubGlobal('caches', {
      keys: async () => {
        throw new Error('storage disabled');
      },
      delete: async () => true,
    });

    await expect(purgeApiCache()).resolves.toBeUndefined();
  });
});
