import { writable } from 'svelte/store';
import { sharesApi } from '../api/client';

export const pendingInvitationCount = writable(0);

export async function refreshInvitationCount() {
  try {
    const invitations = await sharesApi.listInvitations();
    pendingInvitationCount.set(invitations.length);
  } catch {
    // ignore — user may not be authenticated yet
  }
}
