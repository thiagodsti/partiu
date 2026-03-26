<script lang="ts">
  import { onDestroy } from "svelte";
  import { tripsApi, syncApi, failedEmailsApi } from "../api/client";
  import { tripImageBust } from "../lib/tripImageStore";
  import type { Trip, SyncStatus } from "../api/types";
  import { inferTripStatus, timeUntilTrip } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import TripCard from "../components/TripCard.svelte";
  import SyncStatusBar from "../components/SyncStatusBar.svelte";
  import { toasts } from "../lib/toastStore";
  import { t } from "../lib/i18n";
  import { ImageRefreshManager } from "../lib/imageRefresh.svelte";

  // ---- State ----
  let loading = $state(true);
  let error = $state<string | null>(null);
  let tripsList = $state<Trip[]>([]);
  let syncStatus = $state<SyncStatus | null>(null);
  let syncingNow = $state(false);
  let failedEmailCount = $state(0);

  let syncPollInterval: ReturnType<typeof setInterval> | null = null;

  // ---- Load ----
  async function load() {
    loading = true;
    error = null;
    try {
      const [data, status, failed] = await Promise.all([
        tripsApi.list(),
        syncApi.status().catch(() => null),
        failedEmailsApi.list().catch(() => []),
      ]);
      tripsList = data?.trips ?? [];
      syncStatus = status;
      failedEmailCount = failed.length;
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
      toasts.show("Sync started!", "success");
      startSyncPoll();
    } catch (err) {
      toasts.show(`Sync failed: ${(err as Error).message}`, "error");
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
        if (status.status !== "running" || polls > 60) {
          stopSyncPoll();
          if (status.status === "idle") {
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

  // ---- Countdown ticker ----
  let now = $state(Date.now());
  const tickInterval = setInterval(() => { now = Date.now(); }, 60_000);
  onDestroy(() => clearInterval(tickInterval));

  // ---- Image refresh ----
  const imgRefresh = new ImageRefreshManager();

  // ---- Derived ----
  const syncRunning = $derived(syncStatus?.status === "running");
  const activeTrips = $derived(
    tripsList.filter((t) => inferTripStatus(t) !== "completed"),
  );
</script>

<TopNav title={$t("trips.title")} />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t("trips.loading")} />
  {:else if error}
    <EmptyState icon="⚠️" title={$t("trips.load_error")} description={error}>
      <button class="btn btn-primary" onclick={() => load()}
        >{$t("trips.retry")}</button
      >
    </EmptyState>
  {:else}
    <!-- Sync Status Bar -->
    <SyncStatusBar {syncStatus} id="sync-status-bar">
      <a href="#/trips/new" class="btn btn-primary text-sm" style="padding:4px 12px;margin-left:auto">
        + {$t("trips.btn_new_trip")}
      </a>
      <button
        class="btn btn-secondary text-sm"
        style="padding:4px 12px"
        disabled={syncRunning || syncingNow}
        onclick={syncNow}
      >
        {#if syncRunning || syncingNow}
          <span class="spinner"></span>
        {:else}
          {$t("trips.btn_sync")}
        {/if}
      </button>
    </SyncStatusBar>

    <!-- Failed emails warning -->
    {#if failedEmailCount > 0}
      <a href="#/settings" class="failed-emails-banner">
        ⚠️ {$t('trips.failed_emails_warning', { values: { count: failedEmailCount } })}
      </a>
    {/if}

    <!-- Trips List -->
    {#if !loading && activeTrips.length === 0}
      <EmptyState
        title={$t("trips.empty_title")}
        description={$t("trips.empty_desc")}
      >
        <a href="#/trips/new" class="btn btn-primary"
          >{$t("trips.btn_new_trip")}</a
        >
        <a href="#/history" class="btn btn-secondary"
          >{$t("trips.view_history")}</a
        >
        <a href="#/settings" class="btn btn-secondary"
          >{$t("trips.go_settings")}</a
        >
      </EmptyState>
    {:else}
      {#each activeTrips as trip (trip.id)}
        {@const status = inferTripStatus(trip)}
        {@const countdown = status === 'upcoming' && trip.start_date ? timeUntilTrip(trip.start_date, now, $t) : null}
        <TripCard
          {trip}
          href="#/trips/{trip.id}"
          imageUrl={tripImageBust.urlFor(trip.id, $tripImageBust)}
          imgFailed={imgRefresh.imgFailed[trip.id] ?? false}
          refreshing={imgRefresh.refreshingId === trip.id}
          onImageError={(e) => imgRefresh.handleError(e, trip.id)}
          onRefreshImage={(e) => imgRefresh.refresh(e, trip.id)}
        >
          {#snippet badge()}
            <span class="badge badge-{status}">
              {status === "completed"
                ? $t("trips.completed")
                : status === "ongoing"
                  ? $t("trips.ongoing")
                  : $t("trips.upcoming")}
            </span>
          {/snippet}
          {#snippet footer()}
            {#if countdown}
              <span class="countdown">⏳ {countdown}</span>
            {/if}
          {/snippet}
        </TripCard>
      {/each}
    {/if}
  {/if}
</div>

<style>
  .countdown {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--color-accent, #6366f1);
    letter-spacing: 0.01em;
  }

  .failed-emails-banner {
    display: block;
    margin: 6px 16px 0;
    padding: 8px 12px;
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-warning, #f59e0b) 40%, transparent);
    border-radius: 8px;
    color: var(--color-text);
    font-size: 0.85rem;
    text-decoration: none;
  }
  .failed-emails-banner:hover {
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 25%, transparent);
  }
</style>
