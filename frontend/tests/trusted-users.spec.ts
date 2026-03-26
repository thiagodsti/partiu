/**
 * E2E tests for the trusted-users feature:
 * when User B adds User A to their trusted-users list, a trip invitation
 * from User A to User B must be auto-accepted (status = "accepted")
 * without User B needing to manually accept it.
 *
 * Contrast test: without trust, the invitation is "pending" and appears in
 * User B's invitations inbox.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';

// Stable credentials so tests are idempotent when run repeatedly against a dev server
const OWNER_USER = 'e2e_trust_owner';
const OWNER_PASS = 'E2eTrustOwner1!';
const GUEST_USER = 'e2e_trust_guest';
const GUEST_PASS = 'E2eTrustGuest1!';

/** Log in and return an authenticated request context, or null on failure. */
async function loginContext(username: string, password: string): Promise<APIRequestContext | null> {
  const ctx = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const res = await ctx.post('/api/auth/login', { data: { username, password } });
  if (!res.ok()) {
    await ctx.dispose();
    return null;
  }
  return ctx;
}

/**
 * Bootstrap: ensure both test users exist.
 * Tries /api/auth/setup first (fresh CI DB), then falls back to login.
 * Returns an authenticated owner context, or null if setup is impossible.
 */
async function ensureUsers(): Promise<{ ownerCtx: APIRequestContext; guestCtx: APIRequestContext } | null> {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });

  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: OWNER_USER, password: OWNER_PASS, smtp_recipient_address: '' },
  });
  await anon.dispose();

  let ownerCtx: APIRequestContext | null;

  if (setupRes.ok()) {
    ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  } else if (setupRes.status() === 409) {
    ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  } else {
    return null;
  }

  if (!ownerCtx) return null;

  // Ensure the guest user exists (idempotent)
  await ownerCtx.post('/api/users', {
    data: { username: GUEST_USER, password: GUEST_PASS, is_admin: false, smtp_recipient_address: '' },
  });

  const guestCtx = await loginContext(GUEST_USER, GUEST_PASS);
  if (!guestCtx) {
    await ownerCtx.dispose();
    return null;
  }

  return { ownerCtx, guestCtx };
}

// ---------------------------------------------------------------------------
// Test: invitation is auto-accepted when guest trusts the owner
// ---------------------------------------------------------------------------

test('invitation is auto-accepted when invitee trusts the inviter', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping trusted-users tests');

  const { ownerCtx, guestCtx } = users!;

  // Guest adds owner to trusted users
  const trustRes = await guestCtx.post('/api/settings/trusted-users', {
    data: { username: OWNER_USER },
  });
  expect(trustRes.ok()).toBe(true);

  // Owner creates a trip
  const tripRes = await ownerCtx.post('/api/trips', {
    data: { name: 'E2E Trust Auto-Accept Trip', description: '' },
  });
  expect(tripRes.status()).toBe(201);
  const trip = await tripRes.json();

  try {
    // Owner shares the trip with the guest
    const shareRes = await ownerCtx.post(`/api/trips/${trip.id}/share`, {
      data: { username: GUEST_USER },
    });
    expect(shareRes.ok()).toBe(true);

    // The share should have been immediately accepted (no pending invitation)
    const invRes = await guestCtx.get('/api/trips/invitations');
    const invitations = await invRes.json();
    const pendingInv = invitations.find(
      (i: { trip_id: string; status?: string }) => i.trip_id === trip.id,
    );
    // Either no invitation at all, or it has status "accepted" (not "pending")
    if (pendingInv) {
      expect(pendingInv.status).toBe('accepted');
    }

    // Guest can access the trip immediately (as a collaborator) without accepting
    const guestTripRes = await guestCtx.get(`/api/trips/${trip.id}`);
    expect(guestTripRes.ok()).toBe(true);
  } finally {
    // Cleanup: remove trust and delete trip
    const trustListRes = await guestCtx.get('/api/settings/trusted-users');
    if (trustListRes.ok()) {
      const trusted: Array<{ user_id: number; username: string }> = await trustListRes.json();
      const entry = trusted.find((u) => u.username === OWNER_USER);
      if (entry) {
        await guestCtx.delete(`/api/settings/trusted-users/${entry.user_id}`);
      }
    }
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    await guestCtx.dispose();
    await ownerCtx.dispose();
  }
});

// ---------------------------------------------------------------------------
// Test: without trust, invitation remains pending
// ---------------------------------------------------------------------------

test('invitation is pending when invitee does not trust the inviter', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping trusted-users tests');

  const { ownerCtx, guestCtx } = users!;

  // Ensure owner is NOT in guest's trusted list (remove if present)
  const trustListRes = await guestCtx.get('/api/settings/trusted-users');
  if (trustListRes.ok()) {
    const trusted: Array<{ user_id: number; username: string }> = await trustListRes.json();
    const entry = trusted.find((u) => u.username === OWNER_USER);
    if (entry) {
      await guestCtx.delete(`/api/settings/trusted-users/${entry.user_id}`);
    }
  }

  // Owner creates a trip
  const tripRes = await ownerCtx.post('/api/trips', {
    data: { name: 'E2E Trust Pending Trip', description: '' },
  });
  expect(tripRes.status()).toBe(201);
  const trip = await tripRes.json();

  try {
    // Owner shares the trip with the guest
    const shareRes = await ownerCtx.post(`/api/trips/${trip.id}/share`, {
      data: { username: GUEST_USER },
    });
    expect(shareRes.ok()).toBe(true);

    // Guest should have a pending invitation
    const invRes = await guestCtx.get('/api/trips/invitations');
    expect(invRes.ok()).toBe(true);
    const invitations = await invRes.json();
    const inv = invitations.find(
      (i: { trip_id: string }) => i.trip_id === trip.id,
    );
    expect(inv).toBeDefined();

    // Guest cannot access the trip before accepting
    const guestTripRes = await guestCtx.get(`/api/trips/${trip.id}`);
    expect(guestTripRes.status()).toBe(404);
  } finally {
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    await guestCtx.dispose();
    await ownerCtx.dispose();
  }
});

// ---------------------------------------------------------------------------
// Test: adding trust after a pending invitation does NOT retroactively accept it
// (only new invitations after trust is added benefit from auto-accept)
// ---------------------------------------------------------------------------

test('trust added after invitation was sent does not retroactively accept it', async () => {
  const users = await ensureUsers();
  test.skip(!users, 'Could not set up test users — skipping trusted-users tests');

  const { ownerCtx, guestCtx } = users!;

  // Ensure owner is NOT trusted yet
  const trustListRes = await guestCtx.get('/api/settings/trusted-users');
  if (trustListRes.ok()) {
    const trusted: Array<{ user_id: number; username: string }> = await trustListRes.json();
    const entry = trusted.find((u) => u.username === OWNER_USER);
    if (entry) {
      await guestCtx.delete(`/api/settings/trusted-users/${entry.user_id}`);
    }
  }

  // Owner creates a trip and shares it (no trust yet → pending)
  const tripRes = await ownerCtx.post('/api/trips', {
    data: { name: 'E2E Retroactive Trust Trip', description: '' },
  });
  const trip = await tripRes.json();

  try {
    await ownerCtx.post(`/api/trips/${trip.id}/share`, {
      data: { username: GUEST_USER },
    });

    // Confirm invitation is pending
    const invBefore = await guestCtx.get('/api/trips/invitations');
    const invsBefore = await invBefore.json();
    const inv = invsBefore.find((i: { trip_id: string }) => i.trip_id === trip.id);
    expect(inv).toBeDefined();

    // Now guest trusts owner
    await guestCtx.post('/api/settings/trusted-users', { data: { username: OWNER_USER } });

    // Invitation should still be pending (trust is not retroactive)
    const invAfter = await guestCtx.get('/api/trips/invitations');
    const invsAfter = await invAfter.json();
    const invStill = invsAfter.find((i: { trip_id: string }) => i.trip_id === trip.id);
    expect(invStill).toBeDefined();

    // Guest still cannot access the trip until they manually accept
    const accessRes = await guestCtx.get(`/api/trips/${trip.id}`);
    expect(accessRes.status()).toBe(404);
  } finally {
    // Cleanup trust entry
    const cleanupList = await guestCtx.get('/api/settings/trusted-users');
    if (cleanupList.ok()) {
      const trusted: Array<{ user_id: number; username: string }> = await cleanupList.json();
      const entry = trusted.find((u) => u.username === OWNER_USER);
      if (entry) {
        await guestCtx.delete(`/api/settings/trusted-users/${entry.user_id}`);
      }
    }
    await ownerCtx.delete(`/api/trips/${trip.id}`);
    await guestCtx.dispose();
    await ownerCtx.dispose();
  }
});
