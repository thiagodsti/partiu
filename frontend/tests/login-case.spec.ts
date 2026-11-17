/**
 * A username is one account however it is capitalised; a password is not.
 *
 * Every write path already stored the name lowercased, but the lookups compared
 * it byte for byte and two callers (inviting someone to a trip, trusting a
 * user) handed the typed spelling straight through — so "Thiago" was a
 * different person from "thiago" depending on which door you came in by.
 *
 * This signs in as an account global-setup created (stored lowercased, like
 * every account). It used to go through first-run setup instead, which only
 * works on an empty server — and global-setup is what makes a server non-empty,
 * so that version could no longer run anywhere.
 */

import { test, expect } from '@playwright/test';
import { E2E_BROWSER } from './support/accounts';
import { requireSeededServer } from './support/seed';

const BASE_URL = 'http://localhost:8000';

test('a username signs in whatever its case, and the password still does not', async ({
  page,
}) => {
  requireSeededServer();
  const { username, password } = E2E_BROWSER;
  const exact = await page.request.post(`${BASE_URL}/api/auth/login`, { data: { username, password } });
  expect(exact.status()).toBe(200);

  const shouting = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: username.toUpperCase(), password },
  });
  expect(shouting.status()).toBe(200);

  const padded = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: `  ${username} `, password },
  });
  expect(padded.status()).toBe(200);

  // The password is a secret, not an identifier: case is part of it.
  const wrongCasePassword = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username, password: password.toUpperCase() },
  });
  expect(wrongCasePassword.status()).toBe(401);
});
