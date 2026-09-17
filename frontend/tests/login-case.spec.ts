import { test, expect } from '@playwright/test';

/**
 * A username is one account however it is capitalised; a password is not.
 *
 * Every write path already stored the name lowercased, but the lookups compared
 * it byte for byte and two callers (inviting someone to a trip, trusting a
 * user) handed the typed spelling straight through — so "Thiago" was a
 * different person from "thiago" depending on which door you came in by.
 *
 * This drives it through the one door that needs no existing session: first-run
 * setup. On a server that already has an account there is nothing to set up and
 * no password to try, so the test skips rather than guessing credentials.
 */

const BASE_URL = 'http://localhost:8000';
const PASSWORD = 'password1234';

test('a username signs in whatever its case, and the password still does not', async ({
  page,
}) => {
  const me = await page.request.get(`${BASE_URL}/api/auth/me`);
  const firstRun = me.status() === 503 && (await me.json()).setup_required === true;
  test.skip(!firstRun, 'Server already has an account; nothing to set up');

  // Typed with capitals; stored lowercased, which the response confirms.
  const setup = await page.request.post(`${BASE_URL}/api/auth/setup`, {
    data: { username: 'CaseAdmin', password: PASSWORD },
  });
  expect(setup.ok()).toBeTruthy();
  expect((await setup.json()).username).toBe('caseadmin');

  const shouting = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: 'CASEADMIN', password: PASSWORD },
  });
  expect(shouting.status()).toBe(200);

  const padded = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: '  caseadmin ', password: PASSWORD },
  });
  expect(padded.status()).toBe(200);

  // The password is a secret, not an identifier: case is part of it.
  const wrongCasePassword = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { username: 'caseadmin', password: PASSWORD.toUpperCase() },
  });
  expect(wrongCasePassword.status()).toBe(401);
});
