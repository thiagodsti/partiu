import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import type { User } from '../api/types';

const { mockInvitations, mockInboxCount } = vi.hoisted(() => ({
  mockInvitations: vi.fn(),
  mockInboxCount: vi.fn(),
}));

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    UnauthorizedError: actual.UnauthorizedError,
    sharesApi: { listInvitations: mockInvitations },
    notificationsApi: { inboxCount: mockInboxCount },
  };
});

import { UnauthorizedError } from '../api/client';
import { currentUser } from './authStore';
import { pendingInvitationCount, refreshInvitationCount, unreadNotificationCount } from './invitationStore';

/**
 * The bug behind this: App.svelte polls this every 30 s, and it used to run with
 * nobody signed in and swallow the 401. A tab left on the login page, or open
 * after its session expired, hit two endpoints for hours.
 */
describe('refreshInvitationCount', () => {
  beforeEach(() => {
    mockInvitations.mockReset();
    mockInboxCount.mockReset();
    pendingInvitationCount.set(0);
    unreadNotificationCount.set(0);
    window.location.hash = '/trips';
  });

  afterEach(() => currentUser.set(null));

  it('does not call the API when nobody is signed in', async () => {
    currentUser.set(null);

    await refreshInvitationCount();

    expect(mockInvitations).not.toHaveBeenCalled();
    expect(mockInboxCount).not.toHaveBeenCalled();
  });

  it('updates both counts for a signed-in user', async () => {
    currentUser.set({ username: 'alice' } as User);
    mockInvitations.mockResolvedValue([{}, {}]);
    mockInboxCount.mockResolvedValue({ unread: 3 });

    await refreshInvitationCount();

    expect(get(pendingInvitationCount)).toBe(2);
    expect(get(unreadNotificationCount)).toBe(3);
  });

  it('signs the user out and stops polling when the session has expired', async () => {
    currentUser.set({ username: 'alice' } as User);
    pendingInvitationCount.set(1);
    mockInvitations.mockRejectedValue(new UnauthorizedError('Invalid or expired session'));
    mockInboxCount.mockResolvedValue({ unread: 0 });

    await refreshInvitationCount();

    expect(get(currentUser)).toBeNull();
    expect(get(pendingInvitationCount)).toBe(0);
    expect(window.location.hash).toBe('#/login');

    // The next tick of the poll is a no-op.
    mockInvitations.mockClear();
    await refreshInvitationCount();
    expect(mockInvitations).not.toHaveBeenCalled();
  });

  it('keeps the session and the last counts on other errors', async () => {
    currentUser.set({ username: 'alice' } as User);
    pendingInvitationCount.set(4);
    mockInvitations.mockRejectedValue(new Error('HTTP 502'));
    mockInboxCount.mockResolvedValue({ unread: 0 });

    await refreshInvitationCount();

    // Offline or a bad gateway is not a sign-out.
    expect(get(currentUser)).not.toBeNull();
    expect(get(pendingInvitationCount)).toBe(4);
    expect(window.location.hash).toBe('#/trips');
  });
});
