/**
 * E2E tests for a shared trip budget.
 *
 * The scenario the feature exists for: two people travelling together on one
 * purse. Every bill is split between them, so two separate half-budgets would
 * fill in lockstep and tell them nothing; one shared budget counts their
 * combined share and does not care which of them paid.
 *
 * The second half of the story is the one that could not be done at all before:
 * the companion opens the same trip and reads the same bar, without having set
 * anything up themselves.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';

const OWNER_USER = 'e2e_budget_owner';
const OWNER_PASS = 'E2eBudgetOwner1!';
const PARTNER_USER = 'e2e_budget_partner';
const PARTNER_PASS = 'E2eBudgetPartner1!';

async function loginContext(username: string, password: string): Promise<APIRequestContext | null> {
  const ctx = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username, password } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

type Users = { ownerCtx: APIRequestContext; partnerCtx: APIRequestContext } | null;

/* Authenticated once for the whole file rather than per test. Login is rate
 * limited to 5/min per IP, and two sign-ins per test exhausts that by the third
 * one — which shows up as tests silently skipping rather than failing. */
let usersOnce: Promise<Users> | null = null;
function ensureUsers(): Promise<Users> {
  usersOnce ??= createUsers();
  return usersOnce;
}

test.afterAll(async () => {
  const users = await (usersOnce ?? Promise.resolve(null));
  if (users) {
    await users.ownerCtx.dispose();
    await users.partnerCtx.dispose();
  }
});

async function createUsers(): Promise<Users> {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: OWNER_USER, password: OWNER_PASS, smtp_recipient_address: '' },
  });
  await anon.dispose();

  if (!setupRes.ok() && setupRes.status() !== 409) return null;
  const ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  if (!ownerCtx) return null;

  await ownerCtx.post('/api/users', {
    data: { username: PARTNER_USER, password: PARTNER_PASS, is_admin: false, smtp_recipient_address: '' },
  });

  const partnerCtx = await loginContext(PARTNER_USER, PARTNER_PASS);
  if (!partnerCtx) {
    await ownerCtx.dispose();
    return null;
  }
  return { ownerCtx, partnerCtx };
}

/** Share the trip with the partner and have them accept, so both can be tagged
 *  on its expenses — only people on a trip may be. */
async function collaborate(ownerCtx: APIRequestContext, partnerCtx: APIRequestContext, tripId: string) {
  await ownerCtx.post(`/api/trips/${tripId}/share`, { data: { username: PARTNER_USER } });
  const invitations = await (await partnerCtx.get('/api/trips/invitations')).json();
  const invitation = invitations.find((i: { trip_id: string }) => i.trip_id === tripId);
  expect(invitation).toBeDefined();
  await partnerCtx.post(`/api/trips/invitations/${invitation.id}/accept`);
}

test('a shared budget counts both halves of every split, and both people see it', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping shared-budget tests');
  const { ownerCtx, partnerCtx } = users!;

  const trip = await (await ownerCtx.post('/api/trips', { data: { name: 'E2E Shared Budget Trip' } })).json();

  try {
    await collaborate(ownerCtx, partnerCtx, trip.id);

    const participants: { type: string; id: number; name: string }[] = await (
      await ownerCtx.get(`/api/trips/${trip.id}/expenses/participants`)
    ).json();
    const owner = participants.find((p) => p.name === OWNER_USER)!;
    const partner = participants.find((p) => p.name === PARTNER_USER)!;

    // One bill each, both split down the middle. On separate budgets this is
    // 150 apiece; on one shared budget it is the 300 they actually spent.
    await ownerCtx.post(`/api/trips/${trip.id}/expenses`, {
      data: {
        description: 'Hotel',
        amount: 200,
        currency: 'EUR',
        paid_by: { type: 'user', id: owner.id },
        participants: [{ type: 'user', id: owner.id }, { type: 'user', id: partner.id }],
      },
    });
    await partnerCtx.post(`/api/trips/${trip.id}/expenses`, {
      data: {
        description: 'Dinner',
        amount: 100,
        currency: 'EUR',
        paid_by: { type: 'user', id: partner.id },
        participants: [{ type: 'user', id: owner.id }, { type: 'user', id: partner.id }],
      },
    });

    const setRes = await ownerCtx.put(`/api/trips/${trip.id}/budget`, {
      data: {
        amount: 800,
        currency: 'EUR',
        members: [{ type: 'user', id: owner.id }, { type: 'user', id: partner.id }],
      },
    });
    expect(setRes.ok()).toBe(true);

    const ownerBudget = await (await ownerCtx.get(`/api/trips/${trip.id}/budget`)).json();
    expect(ownerBudget.spent).toBe(300);
    expect(ownerBudget.amount).toBe(800);
    expect(ownerBudget.members.map((m: { id: number }) => m.id).sort()).toEqual(
      [owner.id, partner.id].sort(),
    );

    // The point of sharing: the partner set nothing up and reads the same bar.
    const partnerBudget = await (await partnerCtx.get(`/api/trips/${trip.id}/budget`)).json();
    expect(partnerBudget.spent).toBe(300);
    expect(partnerBudget.amount).toBe(800);
    expect(partnerBudget.owner_username).toBe(OWNER_USER);

    // And it reaches the trips list, which reads budgets in bulk.
    const { trips }: { trips: { id: string; budget_spent: number | null }[] } = await (
      await partnerCtx.get('/api/trips')
    ).json();
    expect(trips.find((t) => t.id === trip.id)?.budget_spent).toBe(300);
  } finally {
    await ownerCtx.delete(`/api/trips/${trip.id}`);
  }
});

test('a third person on the bill costs the pair only their share', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping shared-budget tests');
  const { ownerCtx, partnerCtx } = users!;

  const trip = await (await ownerCtx.post('/api/trips', { data: { name: 'E2E Shared Budget Three' } })).json();
  let guestId: number | null = null;

  try {
    await collaborate(ownerCtx, partnerCtx, trip.id);
    guestId = (await (await ownerCtx.post('/api/guests', { data: { name: 'E2E Budget Friend' } })).json()).id;

    const participants: { type: string; id: number; name: string }[] = await (
      await ownerCtx.get(`/api/trips/${trip.id}/expenses/participants`)
    ).json();
    const owner = participants.find((p) => p.name === OWNER_USER)!;
    const partner = participants.find((p) => p.name === PARTNER_USER)!;

    // 90 split three ways: the couple's two thirds is 60, not the whole bill.
    await ownerCtx.post(`/api/trips/${trip.id}/expenses`, {
      data: {
        description: 'Dinner',
        amount: 90,
        currency: 'EUR',
        paid_by: { type: 'user', id: owner.id },
        participants: [
          { type: 'user', id: owner.id },
          { type: 'user', id: partner.id },
          { type: 'guest', id: guestId },
        ],
      },
    });

    await ownerCtx.put(`/api/trips/${trip.id}/budget`, {
      data: {
        amount: 500,
        currency: 'EUR',
        members: [{ type: 'user', id: owner.id }, { type: 'user', id: partner.id }],
      },
    });

    expect((await (await ownerCtx.get(`/api/trips/${trip.id}/budget`)).json()).spent).toBe(60);
  } finally {
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    if (guestId !== null) await ownerCtx.delete(`/api/guests/${guestId}`).catch(() => {});
  }
});

/** The companion you share a purse with usually has no account — that is what
 *  guests are for, so a guest has to be shareable with. */
test('a budget can be shared with a companion who has no account', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping shared-budget tests');
  // No collaborator here: the point is a companion with no account at all.
  const { ownerCtx } = users!;

  const trip = await (await ownerCtx.post('/api/trips', { data: { name: 'E2E Guest Budget Trip' } })).json();
  let guestId: number | null = null;

  try {
    guestId = (await (await ownerCtx.post('/api/guests', { data: { name: 'E2E Budget Spouse' } })).json()).id;
    const me = (await (await ownerCtx.get('/api/auth/me')).json()).id;

    await ownerCtx.post(`/api/trips/${trip.id}/expenses`, {
      data: {
        description: 'Hotel',
        amount: 200,
        currency: 'EUR',
        paid_by: { type: 'user', id: me },
        participants: [{ type: 'user', id: me }, { type: 'guest', id: guestId }],
      },
    });

    await ownerCtx.put(`/api/trips/${trip.id}/budget`, {
      data: {
        amount: 800,
        currency: 'EUR',
        members: [{ type: 'user', id: me }, { type: 'guest', id: guestId }],
      },
    });

    // Their half counts too: the whole 200, not the owner's 100.
    expect((await (await ownerCtx.get(`/api/trips/${trip.id}/budget`)).json()).spent).toBe(200);
  } finally {
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    if (guestId !== null) await ownerCtx.delete(`/api/guests/${guestId}`).catch(() => {});
  }
});

/** Saving an amount without a member list must not silently un-share a budget —
 *  an older client doing exactly that is the realistic way it would happen. */
test('saving an amount alone keeps the members the budget already has', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping shared-budget tests');
  const { ownerCtx, partnerCtx } = users!;

  const trip = await (await ownerCtx.post('/api/trips', { data: { name: 'E2E Budget Keep Members' } })).json();

  try {
    await collaborate(ownerCtx, partnerCtx, trip.id);
    const participants: { type: string; id: number; name: string }[] = await (
      await ownerCtx.get(`/api/trips/${trip.id}/expenses/participants`)
    ).json();
    const owner = participants.find((p) => p.name === OWNER_USER)!;
    const partner = participants.find((p) => p.name === PARTNER_USER)!;

    await ownerCtx.put(`/api/trips/${trip.id}/budget`, {
      data: {
        amount: 800,
        currency: 'EUR',
        members: [{ type: 'user', id: owner.id }, { type: 'user', id: partner.id }],
      },
    });
    await ownerCtx.put(`/api/trips/${trip.id}/budget`, { data: { amount: 900, currency: 'EUR' } });

    const budget = await (await ownerCtx.get(`/api/trips/${trip.id}/budget`)).json();
    expect(budget.amount).toBe(900);
    expect(budget.members.length).toBe(2);
  } finally {
    await ownerCtx.delete(`/api/trips/${trip.id}`);
  }
});
