<script lang="ts">
  import { onDestroy } from 'svelte';
  import { tripsApi, syncApi } from '../api/client';
  import type { Trip, SyncStatus } from '../api/types';
  import { formatDate, formatDateRange, inferTripStatus } from '../lib/utils';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import TopNav from '../components/TopNav.svelte';

  // ---- State ----
  let loading = $state(true);
  let error = $state<string | null>(null);
  let tripsList = $state<Trip[]>([]);
  let syncStatus = $state<SyncStatus | null>(null);
  let syncingNow = $state(false);
  let toasts = $state<{ id: number; message: string; type: string }[]>([]);
  let toastCounter = 0;

  let syncPollInterval: ReturnType<typeof setInterval> | null = null;

  // ---- Load ----
  async function load() {
    loading = true;
    error = null;
    try {
      const [data, status] = await Promise.all([
        tripsApi.list(),
        syncApi.status().catch(() => null),
      ]);
      tripsList = data?.trips ?? [];
      syncStatus = status;
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  // ---- Sync ----
  async function syncNow() {
    syncingNow = true;
    try {
      await syncApi.now();
      showToast('Sync started!', 'success');
      startSyncPoll();
    } catch (err) {
      showToast(`Sync failed: ${(err as Error).message}`, 'error');
    } finally {
      syncingNow = false;
    }
  }

  function startSyncPoll() {
    stopSyncPoll();
    let polls = 0;
    syncPollInterval = setInterval(async () => {
      polls++;
      try {
        const status = await syncApi.status();
        syncStatus = status;
        if (status.status !== 'running' || polls > 60) {
          stopSyncPoll();
          if (status.status === 'idle') {
            const data = await tripsApi.list();
            tripsList = data?.trips ?? [];
          }
        }
      } catch {
        stopSyncPoll();
      }
    }, 2000);
  }

  function stopSyncPoll() {
    if (syncPollInterval) {
      clearInterval(syncPollInterval);
      syncPollInterval = null;
    }
  }

  onDestroy(stopSyncPoll);

  // ---- Toast ----
  function showToast(message: string, type = 'info', duration = 3000) {
    const id = ++toastCounter;
    toasts = [...toasts, { id, message, type }];
    setTimeout(() => {
      toasts = toasts.filter((t) => t.id !== id);
    }, duration);
  }

  // ---- Derived ----
  const syncRunning = $derived(syncStatus?.status === 'running');
  const syncHasError = $derived(syncStatus?.status === 'error');
  const lastSynced = $derived(syncStatus?.last_synced_at);
  const activeTrips = $derived(tripsList.filter(t => inferTripStatus(t) !== 'completed'));
</script>

<TopNav title="✈ My Trips" />

<div class="main-content">
  {#if loading}
    <LoadingScreen message="Loading trips..." />
  {:else if error}
    <EmptyState icon="⚠️" title="Failed to load trips" description={error}>
      <button class="btn btn-primary" onclick={() => load()}>Retry</button>
    </EmptyState>
  {:else}
    <!-- Sync Status Bar -->
    <div class="sync-status-bar" id="sync-status-bar">
      <span class="sync-dot {syncRunning ? 'running' : syncHasError ? 'error' : 'idle'}"></span>
      <span>
        {#if syncRunning}
          Syncing emails...
        {:else if syncHasError}
          Sync error: {syncStatus?.last_error ?? ''}
        {:else if lastSynced}
          Last synced: {formatDate(lastSynced)}
        {:else}
          Never synced
        {/if}
      </span>
      <span style="flex:1"></span>
      <button
        class="btn btn-secondary text-sm"
        style="padding:4px 12px"
        disabled={syncRunning || syncingNow}
        onclick={syncNow}
      >
        {#if syncRunning || syncingNow}
          <span class="spinner"></span>
        {:else}
          ↻ Sync
        {/if}
      </button>
    </div>

    <!-- Trips List -->
    {#if !loading && activeTrips.length === 0}
      <EmptyState
        title="No upcoming flights"
        description="All your trips are in the past. Check History, or configure Gmail in Settings to import new confirmations."
      >
        <a href="#/history" class="btn btn-secondary">View History</a>
        <a href="#/settings" class="btn btn-primary">Go to Settings</a>
      </EmptyState>
    {:else}
      {#each activeTrips as trip (trip.id)}
        {@const status = inferTripStatus(trip)}
        {@const dateRange = formatDateRange(trip.start_date, trip.end_date)}
        {@const flightCount = trip.flight_count ?? 0}
        {@const refs = (trip.booking_refs ?? []).join(', ')}
        <a class="card-link" href="#/trips/{trip.id}">
          <article class="card trip-card">
            <div class="trip-card-header">
              <h2 class="trip-card-title">{trip.name}</h2>
              <span class="badge badge-{status}">
                {status === 'completed' ? 'Completed' : status === 'ongoing' ? 'Ongoing' : 'Upcoming'}
              </span>
            </div>
            {#if dateRange}
              <div class="trip-card-meta">
                <span>📅 {dateRange}</span>
                <span>✈ {flightCount} flight{flightCount !== 1 ? 's' : ''}</span>
              </div>
            {/if}
            <div class="trip-card-footer">
              {#if refs}
                <span class="text-sm text-muted">Ref: {refs}</span>
              {/if}
            </div>
          </article>
        </a>
      {/each}
    {/if}
  {/if}
</div>

<!-- Toast Container -->
{#if toasts.length > 0}
  <div class="toast-container">
    {#each toasts as toast (toast.id)}
      <div class="toast toast-{toast.type}">{toast.message}</div>
    {/each}
  </div>
{/if}
