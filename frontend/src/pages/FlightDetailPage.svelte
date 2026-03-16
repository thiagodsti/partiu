<script lang="ts">
  import { onMount } from 'svelte';
  import { flightsApi, airportsApi } from '../api/client';
  import type { Flight, Airport, AircraftInfo, EmailData } from '../api/types';
  import {
    formatTime,
    formatDate,
    formatDateLong,
    formatTimezone,
    formatDuration,
    cabinLabel,
    seatMapUrl,
  } from '../lib/utils';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import TopNav from '../components/TopNav.svelte';

  interface Props {
    params: { tripId: string; flightId: string };
  }
  const { params }: Props = $props();

  // ---- State ----
  let loading = $state(true);
  let error = $state<string | null>(null);
  let flight = $state<Flight | null>(null);

  // Aircraft
  let aircraftInfo = $state<AircraftInfo | null>(null);
  let aircraftLoading = $state(false);
  let aircraftNotAvailable = $state(false);

  // Airport maps
  let depAirport = $state<Airport | null>(null);
  let arrAirport = $state<Airport | null>(null);
  let depMapOpen = $state(false);
  let arrMapOpen = $state(false);

  // Email modal
  let emailModalOpen = $state(false);
  let emailData = $state<EmailData | null>(null);
  let emailLoading = $state(false);
  let emailError = $state<string | null>(null);

  // ---- Load flight ----
  async function load() {
    loading = true;
    error = null;
    try {
      flight = await flightsApi.get(params.flightId);
      // After flight loads, fetch aircraft and airport maps in parallel
      fetchAircraftInfo();
      fetchAirportMaps();
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  // ---- Aircraft lazy load ----
  async function fetchAircraftInfo() {
    if (!flight) return;
    if (flight.aircraft_type) return; // already cached in DB

    const isCompleted =
      flight.arrival_datetime && new Date(flight.arrival_datetime).getTime() < Date.now();
    if (isCompleted) {
      aircraftNotAvailable = true;
      return;
    }

    aircraftLoading = true;
    try {
      const info = await flightsApi.aircraft(params.flightId);
      if (info && info.type_name) {
        aircraftInfo = info;
      } else {
        aircraftNotAvailable = true;
      }
    } catch {
      aircraftNotAvailable = true;
    } finally {
      aircraftLoading = false;
    }
  }

  // ---- Airport maps ----
  async function fetchAirportMaps() {
    if (!flight) return;
    const [dep, arr] = await Promise.all([
      airportsApi.get(flight.departure_airport).catch(() => null),
      airportsApi.get(flight.arrival_airport).catch(() => null),
    ]);
    depAirport = dep;
    arrAirport = arr;
  }

  function makeOsmEmbedUrl(airport: Airport): string {
    const lat = airport.latitude!;
    const lon = airport.longitude!;
    const d = 0.009;
    const bbox = `${lon - d},${lat - d},${lon + d},${lat + d}`;
    return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}`;
  }

  // ---- Email modal ----
  async function openRawEmail() {
    emailLoading = true;
    emailError = null;
    try {
      emailData = await flightsApi.email(params.flightId);
      emailModalOpen = true;
    } catch (err) {
      emailError = (err as Error).message;
      alert(`Could not load email: ${emailError}`);
    } finally {
      emailLoading = false;
    }
  }

  function closeEmailModal() {
    emailModalOpen = false;
    emailData = null;
  }

  // ---- Derived ----
  const backUrl = $derived(params.tripId ? `#/trips/${params.tripId}` : '#/trips');
  const title = $derived(flight ? `${flight.departure_airport ?? '?'} → ${flight.arrival_airport ?? '?'}` : 'Loading...');
  const duration = $derived(formatDuration(flight?.duration_minutes));
  const depDate = $derived(formatDateLong(flight?.departure_datetime));
  const arrDate = $derived(formatDateLong(flight?.arrival_datetime));
  const showArrDate = $derived(arrDate !== depDate);
  const mapUrl = $derived(seatMapUrl(flight?.aircraft_type));

  // Show aircraft type from either DB or lazy-loaded
  const displayAircraftType = $derived(flight?.aircraft_type ?? aircraftInfo?.type_name ?? null);
  const displayAircraftReg = $derived(flight?.aircraft_registration ?? aircraftInfo?.registration ?? null);
</script>

<TopNav title={title} backHref={backUrl} />

<div class="main-content">
  {#if loading}
    <LoadingScreen message="Loading flight..." />
  {:else if error || !flight}
    <EmptyState icon="⚠️" title="Failed to load flight" description={error ?? 'Unknown error'}>
      <a href={backUrl} class="btn btn-primary">Back</a>
    </EmptyState>
  {:else}
    <!-- Hero card -->
    <div class="flight-detail-hero">
      <div style="display:flex;align-items:center;justify-content:center;gap:var(--space-sm);margin-bottom:var(--space-sm)">
        {#if flight.airline_code}
          <span class="airline-badge airline-{flight.airline_code}">{flight.airline_code}</span>
        {/if}
        <span style="font-size:1.1rem;font-weight:600;font-family:monospace">{flight.flight_number}</span>
        <span class="badge badge-{flight.status ?? 'upcoming'}">{flight.status ?? 'upcoming'}</span>
      </div>

      <div class="flight-detail-route">
        <!-- Departure -->
        <div class="flight-detail-airport">
          <div class="airport-code">{flight.departure_airport}</div>
          <div class="airport-time">{formatTime(flight.departure_datetime, flight.departure_timezone)}</div>
          <div class="airport-date">{depDate}</div>
          {#if flight.departure_timezone}
            <div class="airport-date" style="color:var(--text-muted);font-size:0.7rem">
              {formatTimezone(flight.departure_datetime, flight.departure_timezone) ?? flight.departure_timezone}
            </div>
          {/if}
          {#if flight.departure_terminal}
            <div class="airport-date">Terminal {flight.departure_terminal}</div>
          {/if}
          {#if flight.departure_gate}
            <div class="airport-date">Gate {flight.departure_gate}</div>
          {/if}
        </div>

        <!-- Arrow -->
        <div class="flight-detail-arrow">
          <div class="flight-detail-arrow-line"></div>
          {#if duration}
            <div class="flight-duration">{duration}</div>
          {/if}
        </div>

        <!-- Arrival -->
        <div class="flight-detail-airport">
          <div class="airport-code">{flight.arrival_airport}</div>
          <div class="airport-time">{formatTime(flight.arrival_datetime, flight.arrival_timezone)}</div>
          {#if showArrDate}
            <div class="airport-date">{arrDate}</div>
          {:else}
            <div class="airport-date"></div>
          {/if}
          {#if flight.arrival_timezone}
            <div class="airport-date" style="color:var(--text-muted);font-size:0.7rem">
              {formatTimezone(flight.arrival_datetime, flight.arrival_timezone) ?? flight.arrival_timezone}
            </div>
          {/if}
          {#if flight.arrival_terminal}
            <div class="airport-date">Terminal {flight.arrival_terminal}</div>
          {/if}
          {#if flight.arrival_gate}
            <div class="airport-date">Gate {flight.arrival_gate}</div>
          {/if}
        </div>
      </div>

      <!-- Aircraft badge -->
      <div id="aircraft-badge-container" style="margin-top:var(--space-md)">
        {#if displayAircraftType}
          <div class="aircraft-badge">
            ✈ {displayAircraftType}
            {#if displayAircraftReg}
              <span style="color:var(--text-muted);font-size:0.75rem">({displayAircraftReg})</span>
            {/if}
          </div>
        {:else if aircraftLoading}
          <div style="color:var(--text-muted);font-size:0.8rem">Looking up aircraft...</div>
        {:else if aircraftNotAvailable}
          <span style="color:var(--text-muted);font-size:0.8rem">Aircraft type not available</span>
        {/if}
      </div>
    </div>

    <!-- Detail Grid -->
    <div class="detail-grid">
      {#if flight.airline_name || flight.airline_code}
        <div class="detail-item">
          <div class="detail-label">Airline</div>
          <div class="detail-value">{flight.airline_name ?? flight.airline_code}</div>
        </div>
      {/if}
      {#if flight.flight_number}
        <div class="detail-item">
          <div class="detail-label">Flight</div>
          <div class="detail-value mono">{flight.flight_number}</div>
        </div>
      {/if}
      {#if flight.booking_reference}
        <div class="detail-item">
          <div class="detail-label">Booking Ref</div>
          <div class="detail-value mono">{flight.booking_reference}</div>
        </div>
      {/if}
      {#if flight.passenger_name}
        <div class="detail-item">
          <div class="detail-label">Passenger</div>
          <div class="detail-value">{flight.passenger_name}</div>
        </div>
      {/if}
      {#if flight.seat}
        <div class="detail-item">
          <div class="detail-label">Seat</div>
          <div class="detail-value">{flight.seat}</div>
        </div>
      {/if}
      {#if flight.cabin_class}
        <div class="detail-item">
          <div class="detail-label">Class</div>
          <div class="detail-value">{cabinLabel(flight.cabin_class)}</div>
        </div>
      {/if}
      {#if duration}
        <div class="detail-item">
          <div class="detail-label">Duration</div>
          <div class="detail-value">{duration}</div>
        </div>
      {/if}
      {#if flight.status}
        <div class="detail-item">
          <div class="detail-label">Status</div>
          <div class="detail-value">{flight.status}</div>
        </div>
      {/if}
    </div>

    <!-- Email Source -->
    {#if flight.email_subject}
      <div class="detail-grid" style="margin-top:var(--space-sm)">
        <div class="detail-item" style="grid-column:1/-1">
          <div class="detail-label">Email Source</div>
          <div class="detail-value text-sm" style="color:var(--text-muted)">{flight.email_subject}</div>
          {#if flight.email_date}
            <div class="detail-value text-sm" style="color:var(--text-muted)">{formatDateLong(flight.email_date)}</div>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Notes -->
    {#if flight.notes}
      <div class="card" style="margin-top:var(--space-md)">
        <div class="detail-label">Notes</div>
        <div class="detail-value">{flight.notes}</div>
      </div>
    {/if}

    <!-- Airport Maps -->
    {#if depAirport || arrAirport}
      <div style="margin-top:var(--space-md);display:flex;flex-direction:column;gap:var(--space-sm)">
        {#if depAirport?.latitude && depAirport?.longitude}
          {@const depName = `${depAirport.iata_code} — ${depAirport.name}${depAirport.city_name ? `, ${depAirport.city_name}` : ''}`}
          <button
            class="btn btn-secondary"
            style="width:100%;text-align:left"
            onclick={() => (depMapOpen = !depMapOpen)}
          >
            🗺 Departure Airport Map — {depAirport.iata_code}
          </button>
          {#if depMapOpen}
            <div style="margin-top:var(--space-xs)">
              <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:var(--space-xs)">{depName}</div>
              <iframe
                src={makeOsmEmbedUrl(depAirport)}
                style="width:100%;height:260px;border:1px solid var(--border);border-radius:var(--radius-md)"
                loading="lazy"
                title="{depAirport.name} map"
              ></iframe>
            </div>
          {/if}
        {/if}

        {#if arrAirport?.latitude && arrAirport?.longitude}
          {@const arrName = `${arrAirport.iata_code} — ${arrAirport.name}${arrAirport.city_name ? `, ${arrAirport.city_name}` : ''}`}
          <button
            class="btn btn-secondary"
            style="width:100%;text-align:left"
            onclick={() => (arrMapOpen = !arrMapOpen)}
          >
            🗺 Arrival Airport Map — {arrAirport.iata_code}
          </button>
          {#if arrMapOpen}
            <div style="margin-top:var(--space-xs)">
              <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:var(--space-xs)">{arrName}</div>
              <iframe
                src={makeOsmEmbedUrl(arrAirport)}
                style="width:100%;height:260px;border:1px solid var(--border);border-radius:var(--radius-md)"
                loading="lazy"
                title="{arrAirport.name} map"
              ></iframe>
            </div>
          {/if}
        {/if}
      </div>
    {/if}

    <!-- Action Buttons -->
    <div style="margin-top:var(--space-lg);padding-bottom:var(--space-lg);display:flex;flex-direction:column;gap:var(--space-sm)">
      {#if mapUrl}
        <a
          href={mapUrl}
          target="_blank"
          rel="noopener"
          class="btn btn-secondary"
          style="width:100%;text-align:center;text-decoration:none"
        >
          💺 View Seat Map
        </a>
      {/if}
      <button
        class="btn btn-secondary"
        style="width:100%"
        disabled={emailLoading}
        onclick={openRawEmail}
      >
        {emailLoading ? 'Loading...' : '📧 View Raw Email'}
      </button>
    </div>
  {/if}
</div>

<!-- Email Modal -->
{#if emailModalOpen && emailData}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions a11y_interactive_supports_focus -->
  <div
    role="dialog"
    aria-modal="true"
    aria-label="Email content"
    tabindex="-1"
    style="position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:1000;display:flex;flex-direction:column;overflow:hidden;"
    onclick={(e) => { if (e.target === e.currentTarget) closeEmailModal(); }}
  >
    <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--surface, var(--bg-secondary));border-bottom:1px solid var(--border);flex-shrink:0;">
      <div style="font-size:0.85rem;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">
        {emailData.email_subject ?? 'Raw Email'}
      </div>
      <button
        style="background:none;border:none;color:var(--text-primary);font-size:1.4rem;cursor:pointer;padding:0 0 0 12px;line-height:1;flex-shrink:0;"
        onclick={closeEmailModal}
      >
        ✕
      </button>
    </div>
    <div style="flex:1;overflow:auto;">
      {#if emailData.html_body}
        <iframe
          srcdoc={emailData.html_body}
          style="width:100%;height:100%;border:none;background:#fff;"
          sandbox="allow-same-origin"
          title="Email content"
        ></iframe>
      {:else}
        <pre style="margin:0;padding:16px;font-size:0.75rem;white-space:pre-wrap;word-break:break-all;color:var(--text-primary);">No HTML body available for this flight.</pre>
      {/if}
    </div>
  </div>
{/if}
