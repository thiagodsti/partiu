<script lang="ts">
  import { onDestroy } from "svelte";
  import { tripsApi, syncApi } from "../api/client";
  import { tripImageBust } from "../lib/tripImageStore";
  import type { Trip, SyncStatus } from "../api/types";
  import {
    formatDateTimeLocale,
    formatDateRange,
    inferTripStatus,
  } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import { t } from "../lib/i18n";

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
      showToast("Sync started!", "success");
      startSyncPoll();
    } catch (err) {
      showToast(`Sync failed: ${(err as Error).message}`, "error");
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

  // ---- Toast ----
  function showToast(message: string, type = "info", duration = 3000) {
    const id = ++toastCounter;
    toasts = [...toasts, { id, message, type }];
    setTimeout(() => {
      toasts = toasts.filter((t) => t.id !== id);
    }, duration);
  }

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
  const syncHasError = $derived(syncStatus?.status === "error");
  const lastSynced = $derived(syncStatus?.last_synced_at);
  const activeTrips = $derived(
    tripsList.filter((t) => inferTripStatus(t) !== "completed"),
  );

  const nextSyncLabel = $derived.by(() => {
    if (!syncStatus?.last_synced_at || !syncStatus?.sync_interval_minutes)
      return null;
    const nextMs =
      new Date(syncStatus.last_synced_at).getTime() +
      syncStatus.sync_interval_minutes * 60 * 1000;
    const nowMs = Date.now();
    if (nextMs <= nowMs) return $t("trips.next_sync_at_any_moment");
    const diffMin = Math.round((nextMs - nowMs) / 60000);
    if (diffMin < 1) return $t("trips.next_sync_at_any_moment");
    const h = Math.floor(diffMin / 60);
    const m = diffMin % 60;
    const rel = h > 0 ? `${h}h ${m}m` : `${m}m`;
    const absTime = new Date(nextMs).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
    return $t("trips.next_sync_at", { values: { rel: rel, absTime: absTime } });
  });
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
    <div class="sync-status-bar" id="sync-status-bar">
      <span
        class="sync-dot {syncRunning
          ? 'running'
          : syncHasError
            ? 'error'
            : 'idle'}"
      ></span>
      <span>
        {#if syncRunning}
          {$t("trips.sync_running")}
        {:else if syncHasError}
          {$t("trips.sync_error")}: {syncStatus?.last_error ?? ""}
        {:else if lastSynced}
          {$t("trips.last_sync", {
            values: { time: formatDateTimeLocale(lastSynced) },
          })}
          {#if nextSyncLabel}<span style="opacity:0.6">
              {$t("trips.next_sync", {
                values: { label: nextSyncLabel },
              })}</span
            >{/if}
        {:else}
          {$t("trips.never_synced")}
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
          {$t("trips.btn_sync")}
        {/if}
      </button>
    </div>

    <!-- Trips List -->
    {#if !loading && activeTrips.length === 0}
      <EmptyState
        title={$t("trips.empty_title")}
        description={$t("trips.empty_desc")}
      >
        <a href="#/history" class="btn btn-secondary"
          >{$t("trips.view_history")}</a
        >
        <a href="#/settings" class="btn btn-primary"
          >{$t("trips.go_settings")}</a
        >
      </EmptyState>
    {:else}
      {#each activeTrips as trip (trip.id)}
        {@const status = inferTripStatus(trip)}
        {@const dateRange = formatDateRange(trip.start_date, trip.end_date)}
        {@const flightCount = trip.flight_count ?? 0}
        {@const refs = (trip.booking_refs ?? []).join(", ")}
        <a class="card-link" href="#/trips/{trip.id}">
          <article class="card trip-card">
            <div class="trip-card-cover" class:no-image={imgFailed[trip.id]}>
              {#if imgFailed[trip.id]}
                <span class="trip-card-no-image-icon">✈</span>
              {:else}
                <img
                  src={tripImageBust.urlFor(trip.id, $tripImageBust)}
                  alt=""
                  class="trip-card-cover-img"
                  onerror={(e) => handleImageError(e, trip.id)}
                />
              {/if}
              <button
                class="trip-card-img-refresh"
                title="Find a different image"
                disabled={refreshingImageId === trip.id}
                onclick={(e) => refreshImage(e, trip.id)}
              >
                {refreshingImageId === trip.id ? '…' : '↻'}
              </button>
            </div>
            <div class="trip-card-header">
              <h2 class="trip-card-title">{trip.name}</h2>
              <span class="badge badge-{status}">
                {status === "completed"
                  ? $t("trips.completed")
                  : status === "ongoing"
                    ? $t("trips.ongoing")
                    : $t("trips.upcoming")}
              </span>
            </div>
            {#if dateRange}
              <div class="trip-card-meta">
                <span>📅 {dateRange}</span>
                <span
                  >✈ {flightCount !== 1
                    ? $t("trips.flight_count_plural", {
                        values: { n: flightCount },
                      })
                    : $t("trips.flight_count", {
                        values: { n: flightCount },
                      })}</span
                >
              </div>
            {/if}
            <div class="trip-card-footer">
              {#if refs}
                <span class="text-sm text-muted"
                  >{$t("trips.ref", { values: { refs } })}</span
                >
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
