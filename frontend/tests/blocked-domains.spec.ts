/**
 * E2E tests for the blocked sender domains feature.
 * Admin can list, add, and remove domains that are silently skipped during sync.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';
const ADMIN_USER = 'e2e_blocked_admin';
const ADMIN_PASS = 'E2eBlockedAdmin1!';
const REGULAR_USER = 'e2e_blocked_regular';
const REGULAR_PASS = 'E2eBlockedRegular1!';
const TEST_DOMAIN = 'e2e-test-blocked.com';

async function loginContext(username: string, password: string): Promise<APIRequestContext | null> {
  const ctx = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username, password } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

async function ensureAdmin(): Promise<APIRequestContext | null> {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  await anon.dispose();

  if (setupRes.ok() || setupRes.status() === 409) {
    return loginContext(ADMIN_USER, ADMIN_PASS);
  }
  return null;
}

test('admin can list blocked domains', async () => {
  const adminCtx = await ensureAdmin();
  test.skip(!adminCtx, 'Could not set up admin — skipping blocked-domains tests');

  try {
    const r = await adminCtx!.get('/api/settings/admin/non-flight-domains');
    expect(r.ok()).toBe(true);
    const domains = await r.json();
    expect(Array.isArray(domains)).toBe(true);
    if (domains.length > 0) {
      expect(domains[0]).toHaveProperty('domain');
      expect(domains[0]).toHaveProperty('note');
      expect(domains[0]).toHaveProperty('created_at');
    }
  } finally {
    await adminCtx!.dispose();
  }
});

test('admin can add and remove a blocked domain', async () => {
  const adminCtx = await ensureAdmin();
  test.skip(!adminCtx, 'Could not set up admin — skipping blocked-domains tests');

  try {
    // Add the domain
    const addRes = await adminCtx!.post('/api/settings/admin/non-flight-domains', {
      data: { domain: TEST_DOMAIN, note: 'e2e test' },
    });
    expect(addRes.ok()).toBe(true);
    expect((await addRes.json()).domain).toBe(TEST_DOMAIN);

    // Verify it appears in the list
    const listRes = await adminCtx!.get('/api/settings/admin/non-flight-domains');
    expect(listRes.ok()).toBe(true);
    const domains: Array<{ domain: string }> = await listRes.json();
    expect(domains.some((d) => d.domain === TEST_DOMAIN)).toBe(true);

    // Remove it
    const delRes = await adminCtx!.delete(
      `/api/settings/admin/non-flight-domains/${TEST_DOMAIN}`,
    );
    expect(delRes.ok()).toBe(true);

    // Verify it is gone
    const listAfter = await adminCtx!.get('/api/settings/admin/non-flight-domains');
    const domainsAfter: Array<{ domain: string }> = await listAfter.json();
    expect(domainsAfter.some((d) => d.domain === TEST_DOMAIN)).toBe(false);
  } finally {
    // Cleanup in case test failed mid-way
    await adminCtx!.delete(`/api/settings/admin/non-flight-domains/${TEST_DOMAIN}`);
    await adminCtx!.dispose();
  }
});

test('adding the same domain twice is idempotent', async () => {
  const adminCtx = await ensureAdmin();
  test.skip(!adminCtx, 'Could not set up admin — skipping blocked-domains tests');

  try {
    await adminCtx!.post('/api/settings/admin/non-flight-domains', {
      data: { domain: TEST_DOMAIN },
    });
    const r = await adminCtx!.post('/api/settings/admin/non-flight-domains', {
      data: { domain: TEST_DOMAIN },
    });
    expect(r.ok()).toBe(true);

    const listRes = await adminCtx!.get('/api/settings/admin/non-flight-domains');
    const domains: Array<{ domain: string }> = await listRes.json();
    expect(domains.filter((d) => d.domain === TEST_DOMAIN).length).toBe(1);
  } finally {
    await adminCtx!.delete(`/api/settings/admin/non-flight-domains/${TEST_DOMAIN}`);
    await adminCtx!.dispose();
  }
});

test('non-admin cannot access blocked domains endpoints', async () => {
  const adminCtx = await ensureAdmin();
  test.skip(!adminCtx, 'Could not set up admin — skipping blocked-domains tests');

  // Create a regular user
  await adminCtx!.post('/api/users', {
    data: { username: REGULAR_USER, password: REGULAR_PASS, is_admin: false },
  });
  await adminCtx!.dispose();

  const regularCtx = await loginContext(REGULAR_USER, REGULAR_PASS);
  test.skip(!regularCtx, 'Could not log in as regular user');

  try {
    const listRes = await regularCtx!.get('/api/settings/admin/non-flight-domains');
    expect(listRes.status()).toBe(403);

    const addRes = await regularCtx!.post('/api/settings/admin/non-flight-domains', {
      data: { domain: 'shouldfail.com' },
    });
    expect(addRes.status()).toBe(403);
  } finally {
    await regularCtx!.dispose();
  }
});
