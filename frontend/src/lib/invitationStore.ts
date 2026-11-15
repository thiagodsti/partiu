import { derived, get, writable } from 'svelte/store';
import { notificationsApi, sharesApi, UnauthorizedError } from '../api/client';
import { currentUser } from './authStore';

export const pendingInvitationCount = writable(0);
export const unreadNotificationCount = writable(0);

// Combined badge: invitations + unread notifications
export const totalInboxBadge = derived(
  [pendingInvitationCount, unreadNotificationCount],
  ([$inv, $notif]) => $inv + $notif,
);

/**
 * App.svelte calls this every 30 s and on every navigation. It used to fire
 * whether or not anyone was signed in and swallow the 401, so a tab left on the
 * login page — or open after its session expired — polled two endpoints for
 * hours. On the public demo those 401s were most of the proxy log.
 */
export async function refreshInvitationCount() {
  if (!get(currentUser)) return;
  try {
    const [invitations, countRes] = await Promise.all([
      sharesApi.listInvitations(),
      notificationsApi.inboxCount(),
    ]);
    pendingInvitationCount.set(invitations.length);
    unreadNotificationCount.set(countRes.unread);
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      // The session expired under an open tab: stop polling and send the user
      // to sign in, rather than keep asking for counts the server will refuse.
      currentUser.set(null);
      pendingInvitationCount.set(0);
      unreadNotificationCount.set(0);
      window.location.hash = '/login';
    }
    // anything else (offline, 5xx) — keep the last counts and try again next tick
  }
}
