<script lang="ts">
  import { location } from 'svelte-spa-router';
  import { tripsApi, settingsApi } from '../api/client';
  import { tripImageBust } from '../lib/tripImageStore';
  import type { Trip, Flight } from '../api/types';
  import {
    formatDateRange,
    inferTripStatus,
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
  import ImmichAlbumButton from '../components/ImmichAlbumButton.svelte';
  import TripMap from '../components/TripMap.svelte';
  import { t } from '../lib/i18n';

  interface Props {
    params: { id: string };
  }
  const { params }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let trip = $state<Trip | null>(null);
  let immichConfigured = $state(false);
  let immichBaseUrl = $state('');

  async function load() {
    loading = true;
    error = null;
    try {
      const [t, s] = await Promise.all([
        tripsApi.get(params.id),
        settingsApi.get().catch(() => null),
      ]);
      trip = t;
      immichConfigured = !!(s?.immich_url && s?.immich_api_key_set);
      immichBaseUrl = s?.immich_url?.replace(/\/$/, '') ?? '';
      // If an album ID is stored, verify it still exists in Immich
      if (trip.immich_album_id && immichConfigured) {
        const status = await tripsApi.checkImmichAlbum(params.id).catch(() => null);
        if (status && !status.exists) {
          trip = { ...trip, immich_album_id: null };
        }
      }
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  const fromHistory = $derived($location.startsWith('/history'));
  const backUrl = $derived(fromHistory ? '#/history' : '#/trips');
  const flightBasePath = $derived(fromHistory ? 'history' : 'trips');

  const flightList = $derived<Flight[]>(trip?.flights ?? []);
  const dateRange = $derived(formatDateRange(trip?.start_date, trip?.end_date));
  const airlines = $derived([...new Set(flightList.map((f) => f.airline_code).filter(Boolean))]);
  const legs = $derived(trip ? splitLegs(flightList, trip) : { outbound: flightList, returning: null });

  // ---- Destination image ----
  let refreshingImage = $state(false);
  let imageRetried = false;

  async function handleImageError(e: Event) {
    const cover = (e.currentTarget as HTMLElement).closest('.trip-detail-cover') as HTMLElement;
    if (imageRetried) { cover.style.display = 'none'; return; }
    imageRetried = true;
    try {
      await tripsApi.refreshImage(params.id);
      tripImageBust.bust(params.id);
    } catch {
      cover.style.display = 'none';
    }
  }

  async function refreshImage(e: MouseEvent) {
    e.stopPropagation();
    if (!trip) return;
    refreshingImage = true;
    try {
      await tripsApi.refreshImage(trip.id);
      tripImageBust.bust(trip.id);
    } finally {
      refreshingImage = false;
    }
  }

  const isCompleted = $derived(trip ? inferTripStatus(trip) === 'completed' : false);

</script>

<TopNav title={loading ? $t('trip.loading') : (trip?.name ?? 'Error')} backHref={backUrl} />

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
      <div class="trip-detail-cover" style="display:none">
        <img
          src={tripImageBust.urlFor(trip.id, $tripImageBust)}
          alt=""
          class="trip-detail-cover-img"
          onload={(e) => { ((e.currentTarget as HTMLElement).closest('.trip-detail-cover') as HTMLElement).style.display = ''; }}
          onerror={(e) => handleImageError(e)}
        />
        <button
          class="trip-card-img-refresh"
          title="Find a different image"
          disabled={refreshingImage}
          onclick={refreshImage}
        >
          {refreshingImage ? '…' : '↻'}
        </button>
      </div>
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
      <div style="margin-top:var(--space-md);display:flex;gap:var(--space-sm);flex-wrap:wrap;align-items:center">
        <a href="#/trips/{params.id}/edit" class="btn btn-secondary" style="font-size:0.85rem">
          ✎ {$t('trip.edit')}
        </a>
        <a href="#/trips/{params.id}/add-flight" class="btn btn-secondary" style="font-size:0.85rem">
          + {$t('trip.add_flight')}
        </a>
        {#if flightList.length > 0}
          <a
            href="/api/trips/{params.id}/ical"
            download="{trip.name || 'trip'}.ics"
            class="btn btn-secondary"
            style="font-size:0.85rem"
          >
            📅 {$t('trip.export_ical')}
          </a>
        {/if}
        {#if isCompleted && immichConfigured}
          <ImmichAlbumButton
            tripId={trip.id}
            immichAlbumId={trip.immich_album_id}
            {immichBaseUrl}
            style="display:inline-flex;align-items:center;gap:var(--space-xs);font-size:0.85rem"
            onAlbumCreated={(albumId) => { trip = { ...trip!, immich_album_id: albumId }; }}
          />
        {/if}
      </div>
    </div>

    <!-- Route Map -->
    {#if flightList.length > 0}
      <TripMap flights={flightList} />
    {/if}

    <!-- Flight List -->
    {#if flightList.length === 0}
      <EmptyState title={$t('trip.empty')}>
        <a href="#/trips/{params.id}/add-flight" class="btn btn-primary">{$t('trip.add_flight')}</a>
      </EmptyState>
    {:else}
      <!-- Outbound leg -->
      <LegDivider label={$t('trip.outbound')} flights={legs.outbound} />
      {#each legs.outbound as flight, i (flight.id)}
        <FlightRow {flight} basePath={flightBasePath} />
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
          <FlightRow {flight} basePath={flightBasePath} />
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
