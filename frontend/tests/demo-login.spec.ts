import { test, expect } from '@playwright/test';

/**
 * The demo-instance notice on the login page.
 *
 * Whether it renders depends on how the server under test was started, so
 * these assert the *contract* rather than one of the two states: the panel is
 * shown exactly when `/api/auth/public-config` reports `demo`, and the
 * credentials on it are the ones the server published. Both states pass —
 * DEMO_MODE off (CI's server, and every real install) and on.
 */

const BASE_URL = 'http://localhost:8000';

test('the login page shows the demo credentials iff the server publishes them', async ({ page }) => {
  // Deliberately unauthenticated: this is the one endpoint the login page can
  // reach before anyone has signed in.
  const res = await page.request.get(`${BASE_URL}/api/auth/public-config`);
  expect(res.ok()).toBeTruthy();
  const config = await res.json();

  await page.goto(`${BASE_URL}/#/login`);
  await page.waitForLoadState('networkidle');

  const note = page.locator('.demo-note');
  if (!config.demo) {
    await expect(note).toHaveCount(0);
    // An ordinary install must not advertise a password anywhere on the page.
    expect(await page.locator('body').innerText()).not.toContain('demo1234');
    return;
  }

  await expect(note).toBeVisible();
  const creds = page.locator('.demo-creds dd');
  await expect(creds.nth(0)).toHaveText(config.demo_username);
  await expect(creds.nth(1)).toHaveText(config.demo_password);

  // One click signs the visitor in with exactly those credentials.
  await page.locator('.demo-btn').click();
  await expect(page).toHaveURL(/#\/trips/);
});

test('a demo instance refuses the changes that would lock everyone out', async ({ page }) => {
  const config = await (await page.request.get(`${BASE_URL}/api/auth/public-config`)).json();
  test.skip(!config.demo, 'not a demo instance');

  await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: config.demo_username, password: config.demo_password },
  });

  // Straight at the API, not through the UI: hiding the control is a courtesy,
  // the refusal is the rule.
  const refused = [
    await page.request.post(`${BASE_URL}/api/auth/2fa/enable`, { data: { code: '123456' } }),
    await page.request.post(`${BASE_URL}/api/auth/change-password`, {
      data: { current_password: config.demo_password, new_password: 'hijacked123' },
    }),
    await page.request.post(`${BASE_URL}/api/users`, {
      data: { username: `intruder${Date.now()}`, password: 'password123' },
    }),
  ];
  for (const r of refused) expect(r.status()).toBe(403);

  // And the published password still works afterwards.
  const again = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: config.demo_username, password: config.demo_password },
  });
  expect(again.ok()).toBeTruthy();
});
