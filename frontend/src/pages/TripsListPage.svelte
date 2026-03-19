<script lang="ts">
  import { onDestroy } from "svelte";
  import { tripsApi, syncApi } from "../api/client";
  import { tripImageBust } from "../lib/tripImageStore";
  import type { Trip, SyncStatus } from "../api/types";
  import { inferTripStatus } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import TripCard from "../components/TripCard.svelte";
  import SyncStatusBar from "../components/SyncStatusBar.svelte";
  import { toasts } from "../lib/toastStore";
  import { t } from "../lib/i18n";

  // ---- State ----
  let loading = $state(true);
  let error = $state<string | null>(null);
  let tripsList = $state<Trip[]>([]);
  let syncStatus = $state<SyncStatus | null>(null);
  let syncingNow = $state(false);

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

  // ---- Image refresh ----
  let refreshingImageId = $state<string | null>(null);
  let imgFailed = $state<Record<string, boolean>>({});
  const retriedTrips = new Set<string>();

  async function handleImageError(_e: Event, tripId: string) {
    if (retriedTrips.has(tripId)) {
      imgFailed = { ...imgFailed, [tripId]: true };
      return;
    }
    retriedTrips.add(tripId);
    try {
      await tripsApi.refreshImage(tripId);
      tripImageBust.bust(tripId);
    } catch {
      imgFailed = { ...imgFailed, [tripId]: true };
    }
  }

  async function refreshImage(e: MouseEvent, tripId: string) {
    e.preventDefault();
    e.stopPropagation();
    refreshingImageId = tripId;
    try {
      await tripsApi.refreshImage(tripId);
      imgFailed = { ...imgFailed, [tripId]: false };
      retriedTrips.delete(tripId);
      tripImageBust.bust(tripId);
    } catch {
      // no image found, leave as-is
    } finally {
      refreshingImageId = null;
    }
  }

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
        <TripCard
          {trip}
          href="#/trips/{trip.id}"
          imageUrl={tripImageBust.urlFor(trip.id, $tripImageBust)}
          imgFailed={imgFailed[trip.id] ?? false}
          refreshing={refreshingImageId === trip.id}
          onImageError={(e) => handleImageError(e, trip.id)}
          onRefreshImage={(e) => refreshImage(e, trip.id)}
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
        </TripCard>
      {/each}
    {/if}
  {/if}
</div>

