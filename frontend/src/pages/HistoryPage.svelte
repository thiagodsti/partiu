<script lang="ts">
  import { tripsApi } from '../api/client';
  import type { Trip } from '../api/types';
  import { formatDateRange, inferTripStatus } from '../lib/utils';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import TopNav from '../components/TopNav.svelte';

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

  const completedTrips = $derived(tripsList.filter(t => inferTripStatus(t) === 'completed'));
</script>

<TopNav title="🕐 History" />

<div class="main-content">
  {#if loading}
    <LoadingScreen message="Loading history..." />
  {:else if error}
    <EmptyState icon="⚠️" title="Failed to load history" description={error}>
      <button class="btn btn-primary" onclick={() => load()}>Retry</button>
    </EmptyState>
  {:else if completedTrips.length === 0}
    <EmptyState
      title="No past trips"
      description="Completed trips will appear here."
    />
  {:else}
    {#each completedTrips as trip (trip.id)}
      {@const dateRange = formatDateRange(trip.start_date, trip.end_date)}
      {@const flightCount = trip.flight_count ?? 0}
      {@const refs = (trip.booking_refs ?? []).join(', ')}
      <a class="card-link" href="#/trips/{trip.id}">
        <article class="card trip-card">
          <div class="trip-card-header">
            <h2 class="trip-card-title">{trip.name}</h2>
            <span class="badge badge-completed">Completed</span>
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
</div>
