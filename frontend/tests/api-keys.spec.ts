/**
 * E2E tests for personal API keys.
 *
 * A key is minted from Settings with a button — nothing exists until then —
 * its value is shown once, and it then authenticates a client that carries no
 * session cookie at all, the way a script or another service would. These
 * drive the real server: mint in the UI, read with the key, prove a read-only
 * key cannot write and no key can reach the account, then revoke.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:8000';
const USER = ACCOUNTS.apiKeysUser.username;
const PASS = ACCOUNTS.apiKeysUser.password;

async function ensureUser(): Promise<boolean> {
  const anon = await request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', { data: { username: USER, password: PASS } });
  if (!setupRes.ok() && setupRes.status() !== 409) {
    await anon.dispose();
    return false;
  }
  const login = await anon.post('/api/auth/login', { data: { username: USER, password: PASS } });
  await anon.dispose();
  return login.ok();
}

/** A client with no cookie jar worth the name — only the key it is handed. */
async function keyClient(secret: string): Promise<APIRequestContext> {
  return request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { Authorization: `Bearer ${secret}` },
  });
}

test('a key created in Settings works without a session and stops when revoked', async ({ page }) => {
  test.skip(!(await ensureUser()), 'Could not set up the test user — skipping API key tests');

  await signInPage(page, USER, PASS);

  await page.goto(`${BASE}/#/settings`);
  await page.waitForLoadState('networkidle');
  const panel = page.locator('.api-keys-panel');
  await expect(panel).toBeVisible({ timeout: 15000 });

  // The expiry picker opens on its default rather than the first option.
  await expect(panel.locator('#api-key-expiry')).toHaveValue('90');

  const name = `e2e ${Date.now()}`;
  await panel.locator('#api-key-name').fill(name);
  await panel.locator('#api-key-scope').selectOption('read');
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/api-keys') && r.request().method() === 'POST'),
    panel.getByRole('button', { name: /create key|criar chave/i }).click(),
  ]);

  const secretField = panel.locator('.api-keys-secret');
  await expect(secretField).toBeVisible();
  const secret = await secretField.inputValue();
  expect(secret).toMatch(/^partiu_/);
  const row = panel.locator('.api-keys-item', { hasText: name });
  await expect(row).toBeVisible();
  await expect(row).not.toContainText(secret);

  const client = await keyClient(secret);
  try {
    const me = await client.get('/api/auth/me');
    expect(me.ok()).toBeTruthy();
    expect((await me.json()).username).toBe(USER);
    expect((await client.get('/api/trips')).ok()).toBeTruthy();

    // Read-only: no writes, and no key ever reaches the account surfaces.
    expect((await client.post('/api/trips', { data: { name: 'nope' } })).status()).toBe(403);
    expect((await client.get('/api/api-keys')).status()).toBe(403);
    expect(
      (await client.post('/api/auth/change-password', {
        data: { current_password: PASS, new_password: 'Hijacked123!' },
      })).status(),
    ).toBe(403);

    // Revoke from the UI; the key stops working at once.
    page.once('dialog', (d) => d.accept());
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/api-keys/') && r.request().method() === 'DELETE'),
      row.getByRole('button', { name: /revoke|revogar/i }).click(),
    ]);
    await expect(row).toHaveCount(0);
    expect((await client.get('/api/trips')).status()).toBe(401);
  } finally {
    await client.dispose();
  }
});
