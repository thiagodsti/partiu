<script lang="ts">
  import { onMount } from 'svelte';
  import { notificationsApi, sharesApi } from '../api/client';
  import type { InAppNotification, TripInvitation } from '../api/types';
  import { refreshInvitationCount } from '../lib/invitationStore';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import TopNav from '../components/TopNav.svelte';
  import { t } from '../lib/i18n';

  let loading = $state(true);
  let error = $state<string | null>(null);
  let invitations = $state<TripInvitation[]>([]);
  let notifications = $state<InAppNotification[]>([]);

  async function load() {
    loading = true;
    error = null;
    try {
      [invitations, notifications] = await Promise.all([
        sharesApi.listInvitations(),
        notificationsApi.inbox(),
      ]);
      // Mark all as read when the page is opened
      if (notifications.some((n) => !n.read)) {
        await notificationsApi.markAllRead();
        notifications = notifications.map((n) => ({ ...n, read: true }));
        await refreshInvitationCount();
      }
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  async function accept(shareId: number) {
    await sharesApi.acceptInvitation(shareId);
    invitations = invitations.filter((i) => i.id !== shareId);
    await refreshInvitationCount();
  }

  async function reject(shareId: number) {
    await sharesApi.rejectInvitation(shareId);
    invitations = invitations.filter((i) => i.id !== shareId);
    await refreshInvitationCount();
  }

  async function deleteNotification(id: number) {
    await notificationsApi.deleteNotification(id);
    notifications = notifications.filter((n) => n.id !== id);
  }

  function notifIcon(type: string): string {
    switch (type) {
      case 'new_flight': return '✈';
      case 'failed_parse': return '⚠';
      case 'invitation': return '✉';
      default: return '🔔';
    }
  }

  function formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
</script>

<TopNav title={$t('nav.notifications')} backHref="#/trips" />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t('nav.notifications')} />
  {:else if error}
    <div class="card" style="padding:var(--space-md);color:var(--danger)">{error}</div>
  {:else}
    <!-- ---- Invitations ---- -->
    {#if invitations.length > 0}
      <div class="section-label">{$t('notifications.invitations')}</div>
      {#each invitations as inv (inv.id)}
        <div class="notif-card notif-unread">
          <div class="notif-icon">✉</div>
          <div class="notif-body">
            <div class="notif-title">
              <strong>{inv.invited_by_username}</strong> {$t('notifications.invited_you')} <strong>{inv.trip_name}</strong>
            </div>
            <div class="notif-actions">
              <button class="btn btn-primary btn-sm" onclick={() => accept(inv.id)}>
                {$t('invitations.accept')}
              </button>
              <button class="btn btn-secondary btn-sm" onclick={() => reject(inv.id)}>
                {$t('invitations.reject')}
              </button>
            </div>
          </div>
        </div>
      {/each}
    {/if}

    <!-- ---- Notifications ---- -->
    {#if notifications.length > 0}
      {#if invitations.length > 0}
        <div class="section-label" style="margin-top:var(--space-md)">{$t('notifications.activity')}</div>
      {/if}
      {#each notifications as notif (notif.id)}
        <div class="notif-card {notif.read ? '' : 'notif-unread'}">
          <div class="notif-icon">{notifIcon(notif.type)}</div>
          <div class="notif-body">
            <div class="notif-title">{notif.title}</div>
            {#if notif.body}
              <div class="notif-desc">{notif.body}</div>
            {/if}
            <div class="notif-date">{formatDate(notif.created_at)}</div>
          </div>
          <div class="notif-right">
            {#if notif.url && notif.url !== '/' && notif.url !== '/#/'}
              <a href={notif.url} class="notif-link">{$t('notifications.view')}</a>
            {/if}
            <button
              class="notif-delete"
              aria-label={$t('notifications.delete')}
              onclick={() => deleteNotification(notif.id)}
            >×</button>
          </div>
        </div>
      {/each}
    {/if}

    {#if invitations.length === 0 && notifications.length === 0}
      <div class="empty-state">
        <div style="font-size:2.5rem;margin-bottom:var(--space-sm)">🔔</div>
        <div style="font-weight:600;margin-bottom:var(--space-xs)">{$t('notifications.empty_title')}</div>
        <div style="font-size:0.875rem;color:var(--text-muted)">{$t('notifications.empty_desc')}</div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .section-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    padding: 0 var(--space-xs) var(--space-xs);
    margin-bottom: var(--space-xs);
  }

  .notif-card {
    display: flex;
    align-items: flex-start;
    gap: var(--space-sm);
    padding: var(--space-md);
    border-radius: var(--radius-sm);
    background: var(--bg-card);
    margin-bottom: var(--space-sm);
    border: 1px solid var(--border);
    transition: background 0.15s;
  }

  .notif-unread {
    background: color-mix(in srgb, var(--accent) 8%, var(--bg-card));
    border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
  }

  .notif-icon {
    font-size: 1.25rem;
    flex-shrink: 0;
    width: 2rem;
    text-align: center;
    margin-top: 1px;
  }

  .notif-body {
    flex: 1;
    min-width: 0;
  }

  .notif-title {
    font-size: 0.9rem;
    font-weight: 500;
    margin-bottom: 2px;
    line-height: 1.4;
  }

  .notif-desc {
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-bottom: 4px;
  }

  .notif-date {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .notif-actions {
    display: flex;
    gap: var(--space-sm);
    margin-top: var(--space-sm);
  }

  .notif-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-xs);
    flex-shrink: 0;
  }

  .notif-link {
    font-size: 0.75rem;
    color: var(--accent);
    white-space: nowrap;
  }

  .notif-delete {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 1.25rem;
    line-height: 1;
    padding: 0 2px;
    cursor: pointer;
  }

  .notif-delete:hover {
    color: var(--danger);
  }

  .empty-state {
    text-align: center;
    padding: var(--space-xl) var(--space-md);
    color: var(--text-secondary);
  }
</style>
