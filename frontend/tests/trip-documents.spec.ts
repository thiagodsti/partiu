/**
 * E2E tests for trip document upload, including the regression case:
 * an invited (non-owner) user must be able to upload documents to a shared trip.
 *
 * These tests spin up their own isolated users via the API so they run
 * reliably in CI (fresh DB) and don't depend on seed data.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8000';

// Stable credentials so tests are idempotent when run repeatedly against a dev server
const OWNER_USER = 'e2e_doc_owner';
const OWNER_PASS = 'E2eDocOwner1!';
const GUEST_USER = 'e2e_doc_guest';
const GUEST_PASS = 'E2eDocGuest1!';

/** Log in as username/password and return an authenticated request context. */
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
 * Bootstrap: ensure the owner and guest users exist.
 * Tries /api/auth/setup first (works on a fresh DB); falls back to
 * creating users as admin when the DB already has accounts.
 *
 * Returns an authenticated context for the owner, or null if setup is
 * impossible (e.g. running against a dev server with unknown admin creds).
 */
async function ensureUsers(): Promise<APIRequestContext | null> {
  const anon = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });

  // --- Try first-time setup (works on a fresh CI DB) ---
  const setupRes = await anon.post('/api/auth/setup', {
    data: { username: OWNER_USER, password: OWNER_PASS, smtp_recipient_address: '' },
  });
  await anon.dispose();

  let ownerCtx: APIRequestContext | null;

  if (setupRes.ok()) {
    // Freshly created; the setup response sets the session cookie in this context,
    // but we'll use a fresh login context to keep things explicit.
    ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  } else if (setupRes.status() === 409) {
    // DB already has users — try to log in as the owner
    ownerCtx = await loginContext(OWNER_USER, OWNER_PASS);
  } else {
    return null;
  }

  if (!ownerCtx) return null;

  // Ensure the guest user exists (idempotent — ignore 400 if already created)
  await ownerCtx.post('/api/users', {
    data: { username: GUEST_USER, password: GUEST_PASS, is_admin: false, smtp_recipient_address: '' },
  });

  return ownerCtx;
}

// ---------------------------------------------------------------------------
// Test: owner can upload a document
// ---------------------------------------------------------------------------

test('owner can upload a document to their trip', async () => {
  const ownerCtx = await ensureUsers();
  test.skip(!ownerCtx, 'Could not set up test users — skipping document tests');

  // Create a trip
  const tripRes = await ownerCtx!.post('/api/trips', {
    data: { name: 'E2E Owner Upload Trip', description: '' },
  });
  expect(tripRes.status()).toBe(201);
  const trip = await tripRes.json();

  // Upload a tiny PNG (1×1 white pixel)
  const pngBytes = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );

  const uploadRes = await ownerCtx!.post(`/api/trips/${trip.id}/documents`, {
    multipart: { file: { name: 'test.png', mimeType: 'image/png', buffer: pngBytes } },
  });
  expect(uploadRes.status()).toBe(201);

  // Verify it appears in the list
  const listRes = await ownerCtx!.get(`/api/trips/${trip.id}/documents`);
  const docs = await listRes.json();
  expect(docs.length).toBeGreaterThan(0);

  // Cleanup
  await ownerCtx!.delete(`/api/trips/${trip.id}`);
  await ownerCtx!.dispose();
});

// ---------------------------------------------------------------------------
// Test: invited user can upload — regression for the bug where this returned 404
// ---------------------------------------------------------------------------

test('invited user can upload a document to a shared trip', async () => {
  const ownerCtx = await ensureUsers();
  test.skip(!ownerCtx, 'Could not set up test users — skipping document tests');

  // Create a trip as the owner
  const tripRes = await ownerCtx!.post('/api/trips', {
    data: { name: 'E2E Shared Upload Trip', description: '' },
  });
  expect(tripRes.status()).toBe(201);
  const trip = await tripRes.json();

  // Share the trip with the guest
  const shareRes = await ownerCtx!.post(`/api/trips/${trip.id}/share`, {
    data: { username: GUEST_USER },
  });
  expect(shareRes.ok()).toBe(true);

  // Log in as the guest and accept the invitation
  const guestCtx = await loginContext(GUEST_USER, GUEST_PASS);
  expect(guestCtx).not.toBeNull();

  const invRes = await guestCtx!.get('/api/trips/invitations');
  const invitations = await invRes.json();
  const inv = invitations.find((i: { trip_id: string }) => i.trip_id === trip.id);
  expect(inv).toBeDefined();

  const acceptRes = await guestCtx!.post(`/api/trips/invitations/${inv.id}/accept`);
  expect(acceptRes.ok()).toBe(true);

  // Upload a document as the invited guest — this was the regression (returned 404 before fix)
  const pngBytes = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );

  const uploadRes = await guestCtx!.post(`/api/trips/${trip.id}/documents`, {
    multipart: { file: { name: 'guest-upload.png', mimeType: 'image/png', buffer: pngBytes } },
  });
  expect(uploadRes.status()).toBe(201);

  // Verify the document is visible to both the guest and the owner
  const guestListRes = await guestCtx!.get(`/api/trips/${trip.id}/documents`);
  const guestDocs = await guestListRes.json();
  expect(guestDocs.length).toBeGreaterThan(0);

  const ownerListRes = await ownerCtx!.get(`/api/trips/${trip.id}/documents`);
  const ownerDocs = await ownerListRes.json();
  expect(ownerDocs.length).toBe(guestDocs.length);

  // Cleanup
  await ownerCtx!.delete(`/api/trips/${trip.id}`);
  await guestCtx!.dispose();
  await ownerCtx!.dispose();
});

// ---------------------------------------------------------------------------
// Test: uninvited user cannot upload
// ---------------------------------------------------------------------------

test('uninvited user cannot upload a document', async () => {
  const ownerCtx = await ensureUsers();
  test.skip(!ownerCtx, 'Could not set up test users — skipping document tests');

  const tripRes = await ownerCtx!.post('/api/trips', {
    data: { name: 'E2E Private Trip', description: '' },
  });
  expect(tripRes.status()).toBe(201);
  const trip = await tripRes.json();

  // Log in as the guest (not invited to this trip)
  const guestCtx = await loginContext(GUEST_USER, GUEST_PASS);
  expect(guestCtx).not.toBeNull();

  const pngBytes = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );

  const uploadRes = await guestCtx!.post(`/api/trips/${trip.id}/documents`, {
    multipart: { file: { name: 'unauthorized.png', mimeType: 'image/png', buffer: pngBytes } },
  });
  expect(uploadRes.status()).toBe(404);

  // Cleanup
  await ownerCtx!.delete(`/api/trips/${trip.id}`);
  await guestCtx!.dispose();
  await ownerCtx!.dispose();
});

// ---------------------------------------------------------------------------
// Test: invited user cannot delete a document (owner-only)
// ---------------------------------------------------------------------------

test('invited user cannot delete documents from a shared trip', async () => {
  const ownerCtx = await ensureUsers();
  test.skip(!ownerCtx, 'Could not set up test users — skipping document tests');

  // Owner creates a trip and uploads a document
  const tripRes = await ownerCtx!.post('/api/trips', {
    data: { name: 'E2E Delete Restriction Trip', description: '' },
  });
  const trip = await tripRes.json();

  const pngBytes = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
  const uploadRes = await ownerCtx!.post(`/api/trips/${trip.id}/documents`, {
    multipart: { file: { name: 'owners-doc.png', mimeType: 'image/png', buffer: pngBytes } },
  });
  const docData = await uploadRes.json();

  // Share with guest and accept
  await ownerCtx!.post(`/api/trips/${trip.id}/share`, { data: { username: GUEST_USER } });
  const guestCtx = await loginContext(GUEST_USER, GUEST_PASS);
  const invRes = await guestCtx!.get('/api/trips/invitations');
  const invitations = await invRes.json();
  const inv = invitations.find((i: { trip_id: string }) => i.trip_id === trip.id);
  if (inv) await guestCtx!.post(`/api/trips/invitations/${inv.id}/accept`);

  // Guest tries to delete the owner's document — must be rejected
  const deleteRes = await guestCtx!.delete(`/api/documents/${docData.id}`);
  expect(deleteRes.status()).toBe(404);

  // Cleanup
  await ownerCtx!.delete(`/api/trips/${trip.id}`);
  await guestCtx!.dispose();
  await ownerCtx!.dispose();
});

// ---------------------------------------------------------------------------
// Test: unauthenticated request is rejected
// ---------------------------------------------------------------------------

test('unauthenticated upload is rejected', async () => {
  const ownerCtx = await ensureUsers();
  test.skip(!ownerCtx, 'Could not set up test users — skipping document tests');

  const tripRes = await ownerCtx!.post('/api/trips', {
    data: { name: 'E2E Auth Trip', description: '' },
  });
  const trip = await tripRes.json();

  const anonCtx = await (await import('@playwright/test')).request.newContext({ baseURL: BASE });
  const pngBytes = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
  const uploadRes = await anonCtx.post(`/api/trips/${trip.id}/documents`, {
    multipart: { file: { name: 'anon.png', mimeType: 'image/png', buffer: pngBytes } },
  });
  expect(uploadRes.status()).toBe(401);

  await ownerCtx!.delete(`/api/trips/${trip.id}`);
  await anonCtx.dispose();
  await ownerCtx!.dispose();
});
