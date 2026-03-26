import { derived, writable } from 'svelte/store';
import { notificationsApi, sharesApi } from '../api/client';

export const pendingInvitationCount = writable(0);
export const unreadNotificationCount = writable(0);

// Combined badge: invitations + unread notifications
export const totalInboxBadge = derived(
  [pendingInvitationCount, unreadNotificationCount],
  ([$inv, $notif]) => $inv + $notif,
);

export async function refreshInvitationCount() {
  try {
    const [invitations, countRes] = await Promise.all([
      sharesApi.listInvitations(),
      notificationsApi.inboxCount(),
    ]);
    pendingInvitationCount.set(invitations.length);
    unreadNotificationCount.set(countRes.unread);
  } catch {
    // ignore — user may not be authenticated yet
  }
}
