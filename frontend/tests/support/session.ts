/**
 * Puts a session in a page's browser context without going through the login
 * form. `page.request` shares the context's cookie jar, so the cookie the
 * login response sets is the one the page then browses with.
 *
 * The specs that use this are testing a trip page, not sign-in (`login-case`
 * and `demo-login` cover that). They used to drive the login form and then
 * *skip* when no cookie turned up — which on the CI runner was every time, so
 * five UI tests had quietly never run there. A missing session is now a
 * failure that says why.
 */

import { expect, type Page } from '@playwright/test';

export async function signInPage(page: Page, username: string, password: string): Promise<void> {
  const res = await page.request.post('/api/auth/login', { data: { username, password } });
  expect(res.ok(), `signing in as ${username} answered ${res.status()}`).toBeTruthy();
  const session = (await page.context().cookies()).find((c) => c.name === 'session');
  expect(
    session,
    'the browser did not keep the session cookie — is the server running with SECURE_COOKIES=false?',
  ).toBeDefined();
}
