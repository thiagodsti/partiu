<script lang="ts">
  import { tripsApi } from '../api/client';
  import type { Trip, Flight } from '../api/types';
  import {
    formatDateRange,
    splitLegs,
    dateDividerInfo,
  } from '../lib/utils';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import TopNav from '../components/TopNav.svelte';
  import FlightRow from '../components/FlightRow.svelte';
  import LegDivider from '../components/LegDivider.svelte';
  import ConnectionBadge from '../components/ConnectionBadge.svelte';
  import DateDivider from '../components/DateDivider.svelte';
  import { t } from '../lib/i18n';

  interface Props {
    params: { id: string };
  }
  const { params }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let trip = $state<Trip | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      trip = await tripsApi.get(params.id);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  const flightList = $derived<Flight[]>(trip?.flights ?? []);
  const dateRange = $derived(formatDateRange(trip?.start_date, trip?.end_date));
  const airlines = $derived([...new Set(flightList.map((f) => f.airline_code).filter(Boolean))]);
  const legs = $derived(trip ? splitLegs(flightList, trip) : { outbound: flightList, returning: null });

</script>

<TopNav title={loading ? $t('trip.loading') : (trip?.name ?? 'Error')} backHref="#/trips" />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t('trip.loading')} />
  {:else if error}
    <EmptyState icon="⚠️" title={$t('trip.load_error')} description={error}>
      <a href="#/trips" class="btn btn-primary">{$t('trip.back')}</a>
    </EmptyState>
  {:else if trip}
    <!-- Trip Header -->
    <div class="trip-header">
      <div class="trip-header-route">{trip.name}</div>
      {#if dateRange}
        <div class="trip-header-dates">
          <span>📅 {dateRange}</span>
          <span>✈ {flightList.length !== 1 ? $t('trips.flight_count_plural', { values: { n: flightList.length } }) : $t('trips.flight_count', { values: { n: flightList.length } })}</span>
        </div>
      {/if}
      <div style="margin-top:var(--space-sm);display:flex;gap:var(--space-xs);flex-wrap:wrap">
        {#each airlines as airline}
          <span class="airline-badge airline-{airline}">{airline}</span>
        {/each}
        {#each (trip.booking_refs ?? []) as ref}
          <span class="text-sm text-muted">Ref: {ref}</span>
        {/each}
      </div>
    </div>

    <!-- Flight List -->
    {#if flightList.length === 0}
      <EmptyState title={$t('trip.empty')} />
    {:else}
      <!-- Outbound leg -->
      <LegDivider label={$t('trip.outbound')} flights={legs.outbound} />
      {#each legs.outbound as flight, i (flight.id)}
        <FlightRow {flight} />
        {#if i < legs.outbound.length - 1}
          {@const prev = legs.outbound[i]}
          {@const next = legs.outbound[i + 1]}
          {@const divInfo = dateDividerInfo(prev, next)}
          {#if divInfo}
            <DateDivider {prev} {next} />
          {:else}
            <ConnectionBadge {prev} {next} />
          {/if}
        {/if}
      {/each}

      <!-- Return leg -->
      {#if legs.returning}
        <LegDivider label={$t('trip.return')} flights={legs.returning} />
        {#each legs.returning as flight, i (flight.id)}
          <FlightRow {flight} />
          {#if i < (legs.returning?.length ?? 0) - 1}
            {@const prev = legs.returning[i]}
            {@const next = legs.returning[i + 1]}
            {@const divInfo = dateDividerInfo(prev, next)}
            {#if divInfo}
              <DateDivider {prev} {next} />
            {:else}
              <ConnectionBadge {prev} {next} />
            {/if}
          {/if}
        {/each}
      {/if}
    {/if}
  {/if}
</div>
