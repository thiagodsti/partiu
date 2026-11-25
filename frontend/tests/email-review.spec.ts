/**
 * E2E for the review list: booking emails Partiu could not read.
 *
 * An email from a sender with no rule (MaxMilhas, flight O6 6175 on Avianca
 * Brasil), uploaded through /api/sync/upload-eml, reaches no reader and lands
 * on the review list. From there: the trips-list line, the review page, the
 * form filled by tapping the email's own values, the import into a trip; and
 * "ignore this sender", undone from Settings. The E2E server has no LLM, so
 * "Fill with AI" is shown disabled with its explanation.
 */

import { test, expect, request, type APIRequestContext } from '@playwright/test';
import { ACCOUNTS } from './support/accounts';
import { signInPage } from './support/session';

const USER = ACCOUNTS.reviewUser.username;
const PASS = ACCOUNTS.reviewUser.password;

function eml(flight: string, ref: string, sender: string): Buffer {
  const [code, number] = [flight.slice(0, 2), flight.slice(2)];
  return Buffer.from(
    [
      `From: ${sender}`,
      'To: traveller@example.com',
      `Subject: Sua passagem foi emitida com sucesso - e-ticket ${ref}`,
      'Date: Wed, 07 Nov 2018 13:03:15 +0000',
      `Message-ID: <e2e-review-${Math.random().toString(36).slice(2)}@example.com>`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset="utf-8"',
      '',
      'Sua passagem foi emitida com sucesso',
      `Código da reserva: ${ref}`,
      `Número do voo: ${code}${number}`,
      'Florianópolis (FLN) 16 NOV 15:40 -> São Paulo (GRU) 17:00',
      '',
    ].join('\r\n'),
    'utf-8',
  );
}

async function api(): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000' });
  const res = await ctx.post('/api/auth/login', { data: { username: USER, password: PASS } });
  expect(res.ok()).toBeTruthy();
  return ctx;
}

async function upload(ctx: APIRequestContext, body: Buffer) {
  const res = await ctx.post('/api/sync/upload-eml', {
    multipart: { files: { name: 'booking.eml', mimeType: 'message/rfc822', buffer: body } },
  });
  expect(res.ok()).toBeTruthy();
}

test('an unread booking is reviewed and imported by tapping its values', async ({ page }) => {
  const ctx = await api();
  await upload(ctx, eml('O66175', 'PVNQDY', 'MaxMilhas <contato@maxmilhas.example>'));
  expect((await (await ctx.get('/api/email-review/count')).json()).count).toBeGreaterThan(0);
  await ctx.dispose();

  await signInPage(page, USER, PASS);
  await page.goto('/#/trips');
  await page.getByTestId('review-notice').click();
  const card = page.getByTestId('review-card').filter({ hasText: 'PVNQDY' });
  await expect(card).toBeVisible({ timeout: 15000 });

  // No LLM on this server: the AI button is there, disabled, and explained.
  await expect(card.getByRole('button', { name: /Fill with AI/ })).toBeDisabled();
  await expect(page.getByTestId('ai-unavailable')).toBeVisible();

  await card.getByRole('button', { name: 'Create trip' }).click();
  const field = (label: string) => card.getByLabel(label, { exact: true });
  await field('Flight number').focus();
  await card.getByRole('button', { name: 'O66175' }).click();
  await field('From').focus();
  await card.getByRole('button', { name: 'FLN', exact: true }).click();
  await field('To').focus();
  await card.getByRole('button', { name: 'GRU', exact: true }).click();
  await field('Departure (local time)').fill('2018-11-16T15:40');
  await field('Arrival (local time)').fill('2018-11-16T17:00');
  await expect(field('Flight number')).toHaveValue('O66175');
  await expect(field('From')).toHaveValue('FLN');

  await card.getByRole('button', { name: 'Import' }).click();
  await expect(page).toHaveURL(/#\/trips\/[^/]+$/, { timeout: 15000 });
  await expect(page.getByText('FLN').first()).toBeVisible();
});

test('ignoring a sender is undone from Settings', async ({ page }) => {
  const ctx = await api();
  await upload(ctx, eml('O61234', 'IGNR01', 'Agency <bookings@ignore-me.example>'));
  await ctx.dispose();

  await signInPage(page, USER, PASS);
  await page.goto('/#/review-emails');
  const card = page.getByTestId('review-card').filter({ hasText: 'IGNR01' });
  await expect(card).toBeVisible({ timeout: 15000 });
  page.once('dialog', (d) => d.accept());
  await card.getByRole('button', { name: 'Ignore this sender' }).click();
  await expect(card).toHaveCount(0);

  await page.goto('/#/settings');
  const section = page.getByTestId('ignored-senders');
  const row = section.locator('div', { hasText: 'ignore-me.example' }).last();
  await expect(row).toBeVisible({ timeout: 15000 });
  await section.getByRole('button', { name: 'Stop ignoring' }).click();
  await expect(section.getByText('ignore-me.example')).toHaveCount(0);
});
