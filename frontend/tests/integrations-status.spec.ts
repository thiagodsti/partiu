/**
 * E2E for Settings → Optional integrations, and KDE Itinerary's row in it.
 *
 * KDE Itinerary's extractor is bundled in the Docker image and on by default
 * (parsers/kitinerary.py). The E2E server runs from a checkout, where the
 * binary is usually absent, so this asserts the row is reported and rendered —
 * whichever state it is in — rather than that the binary is installed.
 */

import { test, expect } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

const USER = ACCOUNTS.integrationsAdmin.username;
const PASS = ACCOUNTS.integrationsAdmin.password;

test('the integrations panel reports KDE Itinerary', async ({ page }) => {
  await signInPage(page, USER, PASS);

  const res = await page.request.get('/api/settings/admin/integrations');
  expect(res.ok()).toBeTruthy();
  const rows = (await res.json()) as { key: string; state: string; env_var: string | null }[];
  const kit = rows.find((r) => r.key === 'kitinerary');
  expect(kit, 'kitinerary is listed').toBeTruthy();
  expect(kit!.env_var).toBe('KITINERARY_EXTRACTOR');
  expect(['set', 'unset', 'disabled']).toContain(kit!.state);

  await page.goto('/#/settings');
  const row = page.locator('.integration-row', { hasText: /KDE Itinerary/ });
  await expect(row).toBeVisible({ timeout: 15000 });
});

test('the blocked-sender list is gone', async ({ page }) => {
  await signInPage(page, USER, PASS);
  const res = await page.request.get('/api/settings/admin/non-flight-domains');
  expect([404, 405]).toContain(res.status());
});
