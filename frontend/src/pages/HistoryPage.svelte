<script lang="ts">
  import { tripsApi } from "../api/client";
  import type { Trip } from "../api/types";
  import { tripImageBust } from "../lib/tripImageStore";
  import { formatDateRange, inferTripStatus } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import { t } from "../lib/i18n";

  let loading = $state(true);
  let error = $state<string | null>(null);
  let tripsList = $state<Trip[]>([]);

  async function load() {
    loading = true;
    error = null;
    try {
      const data = await tripsApi.list();
      tripsList = data?.trips ?? [];
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  const completedTrips = $derived(
    tripsList.filter((t) => inferTripStatus(t) === "completed").slice().reverse(),
  );

  // ---- Image refresh ----
  let refreshingImageId = $state<string | null>(null);
  let coverVisible = $state<Record<string, boolean>>({});
  const retriedTrips = new Set<string>();

  async function handleImageError(_e: Event, tripId: string) {
    if (retriedTrips.has(tripId)) {
      coverVisible = { ...coverVisible, [tripId]: false };
      return;
    }
    retriedTrips.add(tripId);
    try {
      await tripsApi.refreshImage(tripId);
      tripImageBust.bust(tripId);
    } catch {
      coverVisible = { ...coverVisible, [tripId]: false };
    }
  }

  async function refreshImage(e: MouseEvent, tripId: string) {
    e.preventDefault();
    e.stopPropagation();
    refreshingImageId = tripId;
    try {
      await tripsApi.refreshImage(tripId);
      tripImageBust.bust(tripId);
    } catch {
      // no image found, leave as-is
    } finally {
      refreshingImageId = null;
    }
  }
</script>

<TopNav title={$t('history.title')} />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t('history.loading')} />
  {:else if error}
    <EmptyState icon="⚠️" title={$t('history.load_error')} description={error}>
      <button class="btn btn-primary" onclick={() => load()}>{$t('history.retry')}</button>
    </EmptyState>
  {:else if completedTrips.length === 0}
    <EmptyState
      title={$t('history.empty_title')}
      description={$t('history.empty_desc')}
    />
  {:else}
    {#each completedTrips as trip (trip.id)}
      {@const dateRange = formatDateRange(trip.start_date, trip.end_date)}
      {@const flightCount = trip.flight_count ?? 0}
      {@const refs = (trip.booking_refs ?? []).join(", ")}
      <a class="card-link" href="#/history/{trip.id}">
        <article class="card trip-card">
          <div class="trip-card-cover" style={coverVisible[trip.id] ? '' : 'display:none'}>
            <img
              src={tripImageBust.urlFor(trip.id, $tripImageBust)}
              alt=""
              class="trip-card-cover-img"
              onload={() => { coverVisible = { ...coverVisible, [trip.id]: true }; }}
              onerror={(e) => handleImageError(e, trip.id)}
            />
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
            <span class="badge badge-completed">{$t('trips.completed')}</span>
          </div>
          {#if dateRange}
            <div class="trip-card-meta">
              <span>📅 {dateRange}</span>
              <span>✈ {flightCount !== 1 ? $t('trips.flight_count_plural', { values: { n: flightCount } }) : $t('trips.flight_count', { values: { n: flightCount } })}</span>
            </div>
          {/if}
          <div class="trip-card-footer">
            {#if refs}
              <span class="text-sm text-muted">{$t('trips.ref', { values: { refs } })}</span>
            {/if}
          </div>
        </article>
      </a>
    {/each}
  {/if}
</div>
