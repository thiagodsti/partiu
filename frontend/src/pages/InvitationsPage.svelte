<script lang="ts">
  import { sharesApi } from '../api/client';
  import type { TripInvitation } from '../api/types';
  import { refreshInvitationCount } from '../lib/invitationStore';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import TopNav from '../components/TopNav.svelte';
  import { t } from '../lib/i18n';

  let loading = $state(true);
  let error = $state<string | null>(null);
  let invitations = $state<TripInvitation[]>([]);

  async function load() {
    loading = true;
    error = null;
    try {
      invitations = await sharesApi.listInvitations();
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

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
</script>

<TopNav title={$t('invitations.title')} backHref="#/trips" />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t('invitations.title')} />
  {:else if error}
    <EmptyState icon="⚠️" title={error} description="">
      <button class="btn btn-primary" onclick={load}>Retry</button>
    </EmptyState>
  {:else if invitations.length === 0}
    <EmptyState title={$t('invitations.empty')} description="" />
  {:else}
    {#each invitations as inv (inv.id)}
      <div class="card" style="margin-bottom:var(--space-sm);padding:var(--space-md)">
        <div style="font-weight:600;margin-bottom:var(--space-xs)">{inv.trip_name}</div>
        <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:var(--space-sm)">
          {$t('trip.shared_by')} {inv.invited_by_username}
        </div>
        <div style="display:flex;gap:var(--space-sm)">
          <button class="btn btn-primary btn-sm" onclick={() => accept(inv.id)}>
            {$t('invitations.accept')}
          </button>
          <button class="btn btn-secondary btn-sm" onclick={() => reject(inv.id)}>
            {$t('invitations.reject')}
          </button>
        </div>
      </div>
    {/each}
  {/if}
</div>
