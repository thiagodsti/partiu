<script lang="ts">
  import { location } from 'svelte-spa-router';
  import { flightsApi, airportsApi, boardingPassesApi } from "../api/client";
  import { currentUser } from "../lib/authStore";
  import ConfirmModal from "../components/ConfirmModal.svelte";
  import type { Flight, Airport, AircraftInfo, EmailData, BoardingPass } from "../api/types";
  import {
    formatTime,
    formatDateLong,
    formatTimezone,
    formatDuration,
    cabinLabel,
    seatMapUrl,
  } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import { t } from "../lib/i18n";

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

  // Boarding passes
  let boardingPasses = $state<BoardingPass[]>([]);
  let boardingPassOverlayId = $state<string | null>(null);
  let uploadingBP = $state(false);

  // ---- Load flight ----
  async function load() {
    loading = true;
    error = null;
    try {
      flight = await flightsApi.get(params.flightId);
      // After flight loads, fetch aircraft, airport maps, and boarding passes in parallel
      fetchAircraftInfo();
      fetchAirportMaps();
      fetchBoardingPasses();
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
      flight.arrival_datetime &&
      new Date(flight.arrival_datetime).getTime() < Date.now();
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

  // ---- Boarding passes ----
  async function fetchBoardingPasses() {
    if (!flight) return;
    try {
      boardingPasses = await boardingPassesApi.list(params.flightId);
    } catch {
      // non-critical, silently ignore
    }
  }

  async function handleBPUpload(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !flight) return;
    uploadingBP = true;
    try {
      await boardingPassesApi.upload(params.flightId, file);
      await fetchBoardingPasses();
    } catch (err) {
      alert(`Upload failed: ${(err as Error).message}`);
    } finally {
      uploadingBP = false;
      input.value = '';
    }
  }

  async function deleteBoardingPass(bpId: string) {
    if (!confirm($t('flight.bp_delete_confirm'))) return;
    await boardingPassesApi.delete(bpId);
    boardingPasses = boardingPasses.filter((bp) => bp.id !== bpId);
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

  // ---- Delete flight ----
  let showDeleteFlightConfirm = $state(false);
  let deletingFlight = $state(false);

  async function confirmDeleteFlight() {
    if (!flight) return;
    deletingFlight = true;
    try {
      await flightsApi.delete(flight.id);
      window.location.hash = params.tripId ? `#/${basePath}/${params.tripId}` : `#/${basePath}`;
    } catch (err) {
      alert((err as Error).message);
    } finally {
      deletingFlight = false;
      showDeleteFlightConfirm = false;
    }
  }

  // ---- Derived ----
  const basePath = $derived($location.startsWith('/history') ? 'history' : 'trips');
  const backUrl = $derived(
    params.tripId ? `#/${basePath}/${params.tripId}` : `#/${basePath}`,
  );
  const title = $derived(
    flight
      ? `${flight.departure_airport ?? "?"} → ${flight.arrival_airport ?? "?"}`
      : $t("flight.loading"),
  );
  const duration = $derived(formatDuration(flight?.duration_minutes));
  const depDate = $derived(formatDateLong(flight?.departure_datetime));
  const arrDate = $derived(formatDateLong(flight?.arrival_datetime));
  const showArrDate = $derived(arrDate !== depDate);
  const mapUrl = $derived(seatMapUrl(flight?.aircraft_type));

  // Show aircraft type from either DB or lazy-loaded
  const displayAircraftType = $derived(
    flight?.aircraft_type ?? aircraftInfo?.type_name ?? null,
  );
  const displayAircraftReg = $derived(
    flight?.aircraft_registration ?? aircraftInfo?.registration ?? null,
  );

  // Live status
  const liveIsCancelled = $derived(flight?.live_status === 'cancelled');
  const liveIsDiverted = $derived(flight?.live_status === 'diverted');
  const liveIsIncident = $derived(flight?.live_status === 'incident');
  const liveDepDelay = $derived((flight?.live_departure_delay ?? 0) > 0 ? flight!.live_departure_delay : null);
  const liveArrDelay = $derived((flight?.live_arrival_delay ?? 0) > 0 ? flight!.live_arrival_delay : null);
  const liveHasData = $derived(flight?.live_status_fetched_at != null);
  const liveIsOnTime = $derived(
    liveHasData && !liveIsCancelled && !liveIsDiverted && !liveIsIncident && !liveDepDelay && !liveArrDelay
      && (flight?.live_status === 'scheduled' || flight?.live_status === 'active')
  );
</script>

<TopNav {title} backHref={backUrl} />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t("flight.loading")} />
  {:else if error || !flight}
    <EmptyState
      icon="⚠️"
      title={$t("flight.load_error")}
      description={error ?? "Unknown error"}
    >
      <a href={backUrl} class="btn btn-primary">{$t("flight.back")}</a>
    </EmptyState>
  {:else}
    <!-- Hero card -->
    <div class="flight-detail-hero">
      <div
        style="display:flex;align-items:center;justify-content:center;gap:var(--space-sm);margin-bottom:var(--space-sm)"
      >
        {#if flight.airline_code}
          <span class="airline-badge airline-{flight.airline_code}"
            >{flight.airline_code}</span
          >
        {/if}
        <span style="font-size:1.1rem;font-weight:600;font-family:monospace"
          >{flight.flight_number}</span
        >
        <span class="badge badge-{flight.status ?? 'upcoming'}"
          >{$t(flight.status ?? $t("flight.status_upcoming"))}</span
        >
      </div>

      <div class="flight-detail-route">
        <!-- Departure -->
        <div class="flight-detail-airport">
          <div class="airport-code">{flight.departure_airport}</div>
          <div class="airport-time">
            {formatTime(flight.departure_datetime, flight.departure_timezone)}
          </div>
          <div class="airport-date">{depDate}</div>
          {#if flight.departure_timezone}
            <div
              class="airport-date"
              style="color:var(--text-muted);font-size:0.7rem"
            >
              {formatTimezone(
                flight.departure_datetime,
                flight.departure_timezone,
              ) ?? flight.departure_timezone}
            </div>
          {/if}
          {#if flight.departure_terminal}
            <div class="airport-date">
              {$t("flight.terminal", {
                values: { t: flight.departure_terminal },
              })}
            </div>
          {/if}
          {#if flight.departure_gate}
            <div class="airport-date">
              {$t("flight.gate", { values: { g: flight.departure_gate } })}
            </div>
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
          <div class="airport-time">
            {formatTime(flight.arrival_datetime, flight.arrival_timezone)}
          </div>
          {#if showArrDate}
            <div class="airport-date">{arrDate}</div>
          {:else}
            <div class="airport-date"></div>
          {/if}
          {#if flight.arrival_timezone}
            <div
              class="airport-date"
              style="color:var(--text-muted);font-size:0.7rem"
            >
              {formatTimezone(
                flight.arrival_datetime,
                flight.arrival_timezone,
              ) ?? flight.arrival_timezone}
            </div>
          {/if}
          {#if flight.arrival_terminal}
            <div class="airport-date">
              {$t("flight.terminal", {
                values: { t: flight.arrival_terminal },
              })}
            </div>
          {/if}
          {#if flight.arrival_gate}
            <div class="airport-date">
              {$t("flight.gate", { values: { g: flight.arrival_gate } })}
            </div>
          {/if}
        </div>
      </div>

      <!-- Aircraft badge -->
      <div id="aircraft-badge-container" style="margin-top:var(--space-md)">
        {#if displayAircraftType}
          <div class="aircraft-badge">
            ✈ {displayAircraftType}
            {#if displayAircraftReg}
              <span style="color:var(--text-muted);font-size:0.75rem"
                >({displayAircraftReg})</span
              >
            {/if}
          </div>
        {:else if aircraftLoading}
          <div style="color:var(--text-muted);font-size:0.8rem">
            {$t("flight.aircraft_loading")}
          </div>
        {:else if aircraftNotAvailable}
          <span style="color:var(--text-muted);font-size:0.8rem"
            >{$t("flight.aircraft_unavailable")}</span
          >
        {/if}
      </div>

      <!-- Live status banner -->
      {#if liveIsCancelled}
        <div class="live-status-banner live-status-cancelled">✕ {$t("flight.live_status_cancelled")}</div>
      {:else if liveIsDiverted}
        <div class="live-status-banner live-status-diverted">⚠ {$t("flight.live_status_diverted")}</div>
      {:else if liveIsIncident}
        <div class="live-status-banner live-status-incident">⚠ {$t("flight.live_status_incident")}</div>
      {:else if liveDepDelay}
        <div class="live-status-banner live-status-delayed">
          ⏱ {$t("flight.live_delay_dep", { values: { minutes: liveDepDelay } })}
          {#if liveArrDelay && liveArrDelay !== liveDepDelay}
            · {$t("flight.live_delay_arr", { values: { minutes: liveArrDelay } })}
          {/if}
        </div>
      {:else if liveIsOnTime}
        <div class="live-status-banner live-status-ontime">✓ {$t("flight.live_on_time")}</div>
      {/if}
    </div>

    <!-- Detail Grid -->
    <div class="detail-grid">
      {#if flight.airline_name || flight.airline_code}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.airline")}</div>
          <div class="detail-value">
            {flight.airline_name ?? flight.airline_code}
          </div>
        </div>
      {/if}
      {#if flight.flight_number}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.number")}</div>
          <div class="detail-value mono">{flight.flight_number}</div>
        </div>
      {/if}
      {#if flight.booking_reference}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.booking_ref")}</div>
          <div class="detail-value mono">{flight.booking_reference}</div>
        </div>
      {/if}
      {#if flight.passenger_name}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.passenger")}</div>
          <div class="detail-value">{flight.passenger_name}</div>
        </div>
      {/if}
      {#if flight.seat}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.seat")}</div>
          <div class="detail-value">{flight.seat}</div>
        </div>
      {/if}
      {#if flight.cabin_class}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.class")}</div>
          <div class="detail-value">{cabinLabel(flight.cabin_class)}</div>
        </div>
      {/if}
      {#if duration}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.duration")}</div>
          <div class="detail-value">{duration}</div>
        </div>
      {/if}
      {#if flight.status}
        <div class="detail-item">
          <div class="detail-label">{$t("flight.status")}</div>
          <div class="detail-value">{$t(flight.status)}</div>
        </div>
      {/if}
    </div>

    <!-- Email Source -->
    {#if flight.email_subject}
      <div class="detail-grid" style="margin-top:var(--space-sm)">
        <div class="detail-item" style="grid-column:1/-1">
          <div class="detail-label">{$t("flight.email_source")}</div>
          <div class="detail-value text-sm" style="color:var(--text-muted)">
            {flight.email_subject}
          </div>
          {#if flight.email_date}
            <div class="detail-value text-sm" style="color:var(--text-muted)">
              {formatDateLong(flight.email_date)}
            </div>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Notes -->
    {#if flight.notes}
      <div class="card" style="margin-top:var(--space-md)">
        <div class="detail-label">{$t("flight.notes")}</div>
        <div class="detail-value">{flight.notes}</div>
      </div>
    {/if}

    <!-- Airport Maps -->
    {#if depAirport || arrAirport}
      <div
        style="margin-top:var(--space-md);display:flex;flex-direction:column;gap:var(--space-sm)"
      >
        {#if depAirport?.latitude && depAirport?.longitude}
          {@const depName = `${depAirport.iata_code} — ${depAirport.name}${depAirport.city_name ? `, ${depAirport.city_name}` : ""}`}
          <button
            class="btn btn-secondary"
            style="width:100%;text-align:left"
            onclick={() => (depMapOpen = !depMapOpen)}
          >
            {$t("flight.dep_map", { values: { code: depAirport.iata_code } })}
          </button>
          {#if depMapOpen}
            <div style="margin-top:var(--space-xs)">
              <div
                style="font-size:0.75rem;color:var(--text-muted);margin-bottom:var(--space-xs)"
              >
                {depName}
              </div>
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
          {@const arrName = `${arrAirport.iata_code} — ${arrAirport.name}${arrAirport.city_name ? `, ${arrAirport.city_name}` : ""}`}
          <button
            class="btn btn-secondary"
            style="width:100%;text-align:left"
            onclick={() => (arrMapOpen = !arrMapOpen)}
          >
            {$t("flight.arr_map", { values: { code: arrAirport.iata_code } })}
          </button>
          {#if arrMapOpen}
            <div style="margin-top:var(--space-xs)">
              <div
                style="font-size:0.75rem;color:var(--text-muted);margin-bottom:var(--space-xs)"
              >
                {arrName}
              </div>
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

    <!-- Boarding Passes -->
    <div style="margin-top:var(--space-md)">
      <div class="detail-label" style="margin-bottom:var(--space-sm)">{$t('flight.boarding_passes')}</div>
      {#if boardingPasses.length > 0}
        <div style="display:flex;flex-direction:column;gap:var(--space-sm)">
          {#each boardingPasses as bp (bp.id)}
            <div style="display:flex;align-items:center;gap:var(--space-sm)">
              <button
                class="btn btn-primary"
                style="flex:1;text-align:left"
                onclick={() => (boardingPassOverlayId = bp.id)}
              >
                🎫 {bp.passenger_name ?? $t('flight.bp_passenger_unknown')}
                {#if bp.seat} · {$t('flight.bp_seat', { values: { seat: bp.seat } })}{/if}
              </button>
              <button
                class="btn btn-secondary"
                style="padding:var(--space-xs) var(--space-sm);font-size:0.85rem"
                onclick={() => deleteBoardingPass(bp.id)}
                title={$t('flight.bp_delete')}
              >✕</button>
            </div>
          {/each}
        </div>
      {:else}
        <div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:var(--space-sm)">
          {$t('flight.bp_none')}
        </div>
      {/if}
      <label
        style="display:inline-flex;align-items:center;gap:var(--space-xs);cursor:pointer;margin-top:var(--space-sm)"
        class="btn btn-secondary"
      >
        {uploadingBP ? $t('flight.bp_uploading') : $t('flight.bp_upload')}
        <input
          type="file"
          accept="image/png,image/jpeg"
          style="display:none"
          disabled={uploadingBP}
          onchange={handleBPUpload}
        />
      </label>
    </div>

    <!-- Action Buttons -->
    <div
      style="margin-top:var(--space-lg);padding-bottom:var(--space-lg);display:flex;flex-direction:column;gap:var(--space-sm)"
    >
      {#if mapUrl}
        <a
          href={mapUrl}
          target="_blank"
          rel="noopener"
          class="btn btn-secondary"
          style="width:100%;text-align:center;text-decoration:none"
        >
          {$t("flight.seat_map")}
        </a>
      {/if}
      <button
        class="btn btn-secondary"
        style="width:100%"
        disabled={emailLoading}
        onclick={openRawEmail}
      >
        {emailLoading ? $t("flight.btn_loading") : $t("flight.view_email")}
      </button>
      {#if String(flight.user_id) === String($currentUser?.id)}
        <button
          class="btn btn-danger"
          style="width:100%"
          disabled={deletingFlight}
          onclick={() => (showDeleteFlightConfirm = true)}
        >
          {$t("flight.delete")}
        </button>
      {/if}
    </div>
  {/if}
</div>

{#if showDeleteFlightConfirm}
  <ConfirmModal
    message={$t("flight.delete_confirm")}
    confirmLabel={$t("flight.delete")}
    cancelLabel="Cancel"
    danger={true}
    onConfirm={confirmDeleteFlight}
    onCancel={() => (showDeleteFlightConfirm = false)}
  />
{/if}

<!-- Boarding Pass Full-Screen Overlay -->
{#if boardingPassOverlayId}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions a11y_interactive_supports_focus -->
  <div
    role="dialog"
    aria-modal="true"
    aria-label={$t('flight.boarding_pass_overlay')}
    tabindex="-1"
    style="position:fixed;inset:0;background:#000;z-index:1000;display:flex;flex-direction:column;"
    onclick={(e) => { if (e.target === e.currentTarget) boardingPassOverlayId = null; }}
  >
    <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;flex-shrink:0;">
      <span style="color:#fff;font-size:0.9rem;opacity:0.7">{$t('flight.boarding_pass_overlay')}</span>
      <button
        style="background:none;border:none;color:#fff;font-size:1.6rem;cursor:pointer;line-height:1;padding:0"
        onclick={() => (boardingPassOverlayId = null)}
      >✕</button>
    </div>
    <div style="flex:1;display:flex;align-items:center;justify-content:center;padding:var(--space-md);overflow:hidden;">
      <img
        src={boardingPassesApi.imageUrl(boardingPassOverlayId)}
        alt={$t('flight.boarding_pass_overlay')}
        style="max-width:100%;max-height:100%;object-fit:contain;border-radius:8px;"
      />
    </div>
  </div>
{/if}

<!-- Email Modal -->
{#if emailModalOpen && emailData}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions a11y_interactive_supports_focus -->
  <div
    role="dialog"
    aria-modal="true"
    aria-label="Email content"
    tabindex="-1"
    style="position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:1000;display:flex;flex-direction:column;overflow:hidden;"
    onclick={(e) => {
      if (e.target === e.currentTarget) closeEmailModal();
    }}
  >
    <div
      style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--surface, var(--bg-secondary));border-bottom:1px solid var(--border);flex-shrink:0;"
    >
      <div
        style="font-size:0.85rem;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1"
      >
        {emailData.email_subject ?? $t("flight.raw_email_title")}
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
        <pre
          style="margin:0;padding:16px;font-size:0.75rem;white-space:pre-wrap;word-break:break-all;color:var(--text-primary);">{$t(
            "flight.no_html",
          )}</pre>
      {/if}
    </div>
  </div>
{/if}
