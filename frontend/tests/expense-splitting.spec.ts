/**
 * E2E tests for expense splitting: paid-by (user or guest), split-between
 * participants (users + guests), and the resulting per-currency balances.
 *
 * Mirrors the scenario from the feature design: a 100 EUR lunch paid by the
 * trip owner, split 4 ways between the owner, their collaborator (spouse) and
 * two guests — the owner should net +75, everyone else -25.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';

const OWNER_USER = 'e2e_split_owner';
const OWNER_PASS = 'E2eSplitOwner1!';
const SPOUSE_USER = 'e2e_split_spouse';
const SPOUSE_PASS = 'E2eSplitSpouse1!';

async function loginContext(username: string, password: string): Promise<APIRequestContext | null> {
  const ctx = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username, password } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

async function ensureUsers(): Promise<{ ownerCtx: APIRequestContext; spouseCtx: APIRequestContext } | null> {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });

  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: OWNER_USER, password: OWNER_PASS, smtp_recipient_address: '' },
  });
  await anon.dispose();

  let ownerCtx: APIRequestContext | null;
  if (setupRes.ok() || setupRes.status() === 409) {
    ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  } else {
    return null;
  }
  if (!ownerCtx) return null;

  await ownerCtx.post('/api/users', {
    data: { username: SPOUSE_USER, password: SPOUSE_PASS, is_admin: false, smtp_recipient_address: '' },
  });

  const spouseCtx = await loginContext(SPOUSE_USER, SPOUSE_PASS);
  if (!spouseCtx) {
    await ownerCtx.dispose();
    return null;
  }

  return { ownerCtx, spouseCtx };
}

test('lunch split between owner, spouse and two guests nets the expected balances', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping expense-splitting tests');
  const { ownerCtx, spouseCtx } = users!;

  const tripRes = await ownerCtx.post('/api/trips', { data: { name: 'E2E Split Trip' } });
  expect(tripRes.status()).toBe(201);
  const trip = await tripRes.json();

  const guestIds: number[] = [];

  try {
    // Owner shares the trip with their spouse and the spouse accepts
    await ownerCtx.post(`/api/trips/${trip.id}/share`, { data: { username: SPOUSE_USER } });
    const invRes = await spouseCtx.get('/api/trips/invitations');
    const invitations = await invRes.json();
    const invitation = invitations.find((i: { trip_id: string }) => i.trip_id === trip.id);
    expect(invitation).toBeDefined();
    await spouseCtx.post(`/api/trips/invitations/${invitation.id}/accept`);

    // Two guests
    for (const name of ['E2E Friend One', 'E2E Friend Two']) {
      const guestRes = await ownerCtx.post('/api/guests', { data: { name } });
      expect(guestRes.status()).toBe(201);
      guestIds.push((await guestRes.json()).id);
    }

    // Participants picker should list owner + spouse + both guests
    const participantsRes = await ownerCtx.get(`/api/trips/${trip.id}/expenses/participants`);
    const participants: { type: string; id: number; name: string }[] = await participantsRes.json();
    expect(participants.length).toBe(4);
    const ownerParticipant = participants.find((p) => p.name === OWNER_USER);
    const spouseParticipant = participants.find((p) => p.name === SPOUSE_USER);
    expect(ownerParticipant).toBeDefined();
    expect(spouseParticipant).toBeDefined();

    // 100 EUR lunch, paid by owner, split 4 ways
    const expenseRes = await ownerCtx.post(`/api/trips/${trip.id}/expenses`, {
      data: {
        description: 'Lunch',
        amount: 100,
        currency: 'EUR',
        paid_by: { type: 'user', id: ownerParticipant!.id },
        participants: [
          { type: 'user', id: ownerParticipant!.id },
          { type: 'user', id: spouseParticipant!.id },
          { type: 'guest', id: guestIds[0] },
          { type: 'guest', id: guestIds[1] },
        ],
      },
    });
    expect(expenseRes.status()).toBe(201);

    const balancesRes = await ownerCtx.get(`/api/trips/${trip.id}/expenses/balances`);
    expect(balancesRes.ok()).toBe(true);
    const { balances } = await balancesRes.json();
    const eur: { type: string; id: number; net: number }[] = balances.EUR;
    const netOf = (type: string, id: number) => eur.find((e) => e.type === type && e.id === id)?.net;

    expect(netOf('user', ownerParticipant!.id)).toBe(75);
    expect(netOf('user', spouseParticipant!.id)).toBe(-25);
    expect(netOf('guest', guestIds[0])).toBe(-25);
    expect(netOf('guest', guestIds[1])).toBe(-25);
  } finally {
    for (const guestId of guestIds) {
      await ownerCtx.delete(`/api/guests/${guestId}`).catch(() => {});
    }
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    await ownerCtx.dispose();
    await spouseCtx.dispose();
  }
});

test('a guest cannot be deleted while referenced by an expense', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping expense-splitting tests');
  const { ownerCtx, spouseCtx } = users!;

  const tripRes = await ownerCtx.post('/api/trips', { data: { name: 'E2E Guest Lock Trip' } });
  const trip = await tripRes.json();
  const guestRes = await ownerCtx.post('/api/guests', { data: { name: 'E2E Locked Guest' } });
  const guestId = (await guestRes.json()).id;

  try {
    await ownerCtx.post(`/api/trips/${trip.id}/expenses`, {
      data: {
        description: 'Cab',
        amount: 30,
        currency: 'EUR',
        paid_by: { type: 'guest', id: guestId },
      },
    });

    const deleteRes = await ownerCtx.delete(`/api/guests/${guestId}`);
    expect(deleteRes.status()).toBe(400);
  } finally {
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    await ownerCtx.dispose();
    await spouseCtx.dispose();
  }
});

test('a guest tagged on one trip does not show up on an unrelated trip', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping expense-splitting tests');
  const { ownerCtx, spouseCtx } = users!;

  const tripARes = await ownerCtx.post('/api/trips', { data: { name: 'E2E Scoping Trip A' } });
  const tripBRes = await ownerCtx.post('/api/trips', { data: { name: 'E2E Scoping Trip B' } });
  const tripA = await tripARes.json();
  const tripB = await tripBRes.json();
  const guestRes = await ownerCtx.post('/api/guests', { data: { name: 'E2E Scoped Guest' } });
  const guestId = (await guestRes.json()).id;

  try {
    await ownerCtx.post(`/api/trips/${tripA.id}/expenses`, {
      data: { description: 'Cab', amount: 30, currency: 'EUR', paid_by: { type: 'guest', id: guestId } },
    });

    const participantsA = await (await ownerCtx.get(`/api/trips/${tripA.id}/expenses/participants`)).json();
    const participantsB = await (await ownerCtx.get(`/api/trips/${tripB.id}/expenses/participants`)).json();

    expect(participantsA.some((p: { type: string; id: number }) => p.type === 'guest' && p.id === guestId)).toBe(true);
    expect(participantsB.some((p: { type: string; id: number }) => p.type === 'guest' && p.id === guestId)).toBe(false);
  } finally {
    await ownerCtx.delete(`/api/trips/${tripA.id}`);
    await ownerCtx.delete(`/api/trips/${tripB.id}`);
    await ownerCtx.dispose();
    await spouseCtx.dispose();
  }
});
