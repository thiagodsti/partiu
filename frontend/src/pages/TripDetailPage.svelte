<script lang="ts">
  import { location } from 'svelte-spa-router';
  import { tripsApi, settingsApi, tripDocumentsApi, sharesApi } from '../api/client';
  import { tripImageBust } from '../lib/tripImageStore';
  import type { Trip, Flight, TripDocument, TripShare } from '../api/types';
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
  import ConfirmModal from '../components/ConfirmModal.svelte';
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
      loadDocuments();
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

  // ---- Documents ----
  let documents = $state<TripDocument[]>([]);
  let docUploading = $state(false);
  let docUploadError = $state<string | null>(null);
  let viewingDoc = $state<TripDocument | null>(null);
  let viewingPage = $state(0);

  async function loadDocuments() {
    if (!trip) return;
    documents = await tripDocumentsApi.list(trip.id).catch(() => []);
  }

  async function handleDocUpload(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file || !trip) return;
    (e.currentTarget as HTMLInputElement).value = '';
    docUploading = true;
    docUploadError = null;
    try {
      await tripDocumentsApi.upload(trip.id, file);
      await loadDocuments();
    } catch (err) {
      docUploadError = (err as Error).message || $t('trip.doc_upload_error');
    } finally {
      docUploading = false;
    }
  }

  async function deleteDoc(docId: string) {
    if (!confirm($t('trip.doc_delete_confirm'))) return;
    await tripDocumentsApi.delete(docId);
    documents = documents.filter((d) => d.id !== docId);
    if (viewingDoc?.id === docId) viewingDoc = null;
  }

  function openDoc(doc: TripDocument) {
    viewingDoc = doc;
    viewingPage = 0;
  }

  // ---- Delete trip ----
  let showDeleteConfirm = $state(false);
  let deleting = $state(false);

  async function confirmDeleteTrip() {
    if (!trip) return;
    deleting = true;
    try {
      await tripsApi.delete(trip.id);
      window.location.hash = '/';
    } catch (err) {
      alert((err as Error).message);
    } finally {
      deleting = false;
      showDeleteConfirm = false;
    }
  }

  // ---- Share trip ----
  let showSharePanel = $state(false);
  let shareUsername = $state('');
  let shareError = $state<string | null>(null);
  let shareSuccess = $state<string | null>(null);
  let sharing = $state(false);
  let collaborators = $state<TripShare[]>([]);

  async function loadCollaborators() {
    if (!trip || trip.is_owner === false) return;
    collaborators = await sharesApi.listTripShares(trip.id).catch(() => []);
  }

  async function handleShare() {
    if (!trip || !shareUsername.trim()) return;
    sharing = true;
    shareError = null;
    shareSuccess = null;
    try {
      const invited = shareUsername.trim();
      await sharesApi.shareTrip(trip.id, invited);
      shareUsername = '';
      shareSuccess = `Invitation sent to ${invited}`;
      await loadCollaborators();
    } catch (err) {
      shareError = (err as Error).message;
    } finally {
      sharing = false;
    }
  }

  async function revokeCollaborator(userId: number) {
    if (!trip) return;
    await sharesApi.revokeTripShare(trip.id, userId);
    collaborators = collaborators.filter((c) => c.user_id !== userId);
  }

  // ---- Leave shared trip (non-owner) ----
  let leaving = $state(false);

  async function leaveTrip() {
    if (!trip || !confirm($t('trip.leave_confirm'))) return;
    leaving = true;
    try {
      await sharesApi.leaveTrip(trip.id);
      window.location.hash = '/trips';
    } catch (err) {
      alert((err as Error).message);
    } finally {
      leaving = false;
    }
  }

  $effect(() => {
    if (trip && showSharePanel) {
      loadCollaborators();
    }
  });

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
      {#if trip.is_owner === false && trip.owner_username}
        <div style="margin-top:var(--space-sm);font-size:0.8rem;color:var(--text-muted)">
          {$t('trip.shared_by')} {trip.owner_username}
        </div>
      {/if}
      <div style="margin-top:var(--space-md);display:flex;gap:var(--space-sm);flex-wrap:wrap;align-items:center">
        {#if trip.is_owner !== false}
          <a href="#/trips/{params.id}/edit" class="btn btn-secondary" style="font-size:0.85rem">
            ✎ {$t('trip.edit')}
          </a>
          <a href="#/trips/{params.id}/add-flight" class="btn btn-secondary" style="font-size:0.85rem">
            + {$t('trip.add_flight')}
          </a>
        {/if}
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
        {#if trip.is_owner !== false}
          <button
            class="btn btn-secondary"
            style="font-size:0.85rem"
            onclick={() => { showSharePanel = !showSharePanel; }}
          >
            ⤷ {$t('trip.share')}
          </button>
          <button
            class="btn btn-danger"
            style="font-size:0.85rem"
            disabled={deleting}
            onclick={() => (showDeleteConfirm = true)}
          >
            🗑 {$t('trip.delete')}
          </button>
        {:else}
          <button
            class="btn btn-secondary"
            style="font-size:0.85rem"
            disabled={leaving}
            onclick={leaveTrip}
          >
            ✕ {$t('trip.leave')}
          </button>
        {/if}
      </div>

      {#if showSharePanel && trip.is_owner !== false}
        <div class="share-panel" style="margin-top:var(--space-md)">
          <h4 style="margin:0 0 var(--space-sm)">{$t('trip.collaborators')}</h4>
          <div style="display:flex;gap:var(--space-xs);margin-bottom:var(--space-sm)">
            <input
              type="text"
              class="form-input"
              placeholder={$t('trip.share_username_placeholder')}
              bind:value={shareUsername}
              oninput={() => { shareSuccess = null; shareError = null; }}
              style="flex:1;min-width:0"
            />
            <button class="btn btn-primary btn-sm" disabled={sharing || !shareUsername.trim()} onclick={handleShare}>
              {sharing ? '…' : $t('trip.share_invite')}
            </button>
          </div>
          {#if shareError}
            <p style="color:var(--danger);font-size:0.85rem;margin:var(--space-xs) 0 0">{shareError}</p>
          {/if}
          {#if shareSuccess}
            <p style="color:var(--success);font-size:0.85rem;margin:var(--space-xs) 0 0">✓ {shareSuccess}</p>
          {/if}
          {#if collaborators.length > 0}
            <ul style="list-style:none;padding:0;margin:0">
              {#each collaborators as collab (collab.user_id)}
                <li style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-xs) 0;gap:var(--space-sm)">
                  <span style="display:flex;align-items:center;gap:var(--space-xs)">
                    {collab.username}
                    <span style="font-size:0.75rem;padding:2px 6px;border-radius:10px;background:var(--{collab.status === 'accepted' ? 'success' : 'warning'}-bg, {collab.status === 'accepted' ? '#d1fae5' : '#fef3c7'});color:{collab.status === 'accepted' ? 'var(--success, #065f46)' : 'var(--warning-text, #92400e)'}">
                      {$t(`trip.share_status_${collab.status}`)}
                    </span>
                  </span>
                  <button
                    class="btn btn-danger btn-sm"
                    onclick={() => revokeCollaborator(collab.user_id)}
                  >
                    {$t('trip.revoke_access')}
                  </button>
                </li>
              {/each}
            </ul>
          {:else}
            <p style="font-size:0.85rem;color:var(--text-muted)">No collaborators yet.</p>
          {/if}
        </div>
      {/if}
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

    <!-- Documents -->
    <div class="trip-section">
      <div class="trip-section-header">
        <h3 class="trip-section-title">{$t('trip.documents')}</h3>
        <label class="btn btn-secondary btn-sm" class:disabled={docUploading}>
          {docUploading ? $t('trip.doc_uploading') : $t('trip.doc_add')}
          <input
            type="file"
            accept=".pdf,image/png,image/jpeg,image/webp"
            style="display:none"
            disabled={docUploading}
            onchange={handleDocUpload}
          />
        </label>
      </div>
      {#if docUploadError}
        <p class="doc-upload-error">{docUploadError}</p>
      {/if}
      {#if documents.length === 0}
        <p class="doc-empty">{$t('trip.doc_empty')}</p>
      {:else}
        <div class="doc-grid">
          {#each documents as doc (doc.id)}
            <button class="doc-thumb" onclick={() => openDoc(doc)}>
              <img src={tripDocumentsApi.viewUrl(doc.id)} alt={doc.filename} loading="lazy" />
              <span class="doc-thumb-name">{doc.filename}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

{#if showDeleteConfirm}
  <ConfirmModal
    message={$t('trip.delete_confirm')}
    confirmLabel={$t('trip.delete')}
    cancelLabel="Cancel"
    danger={true}
    onConfirm={confirmDeleteTrip}
    onCancel={() => (showDeleteConfirm = false)}
  />
{/if}

<!-- Document viewer modal -->
{#if viewingDoc}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="doc-modal-overlay" role="presentation" onclick={() => (viewingDoc = null)}>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div class="doc-modal" role="dialog" aria-modal="true" tabindex="-1" onclick={(e) => e.stopPropagation()}>
      <div class="doc-modal-header">
        <span class="doc-modal-name">{viewingDoc.filename}</span>
        <div class="doc-modal-actions">
          {#if viewingDoc.page_count > 1}
            <button
              class="btn btn-secondary btn-sm"
              disabled={viewingPage === 0}
              onclick={() => viewingPage--}
            >‹</button>
            <span class="doc-page-label">
              {$t('trip.doc_page', { values: { current: viewingPage + 1, total: viewingDoc.page_count } })}
            </span>
            <button
              class="btn btn-secondary btn-sm"
              disabled={viewingPage >= viewingDoc.page_count - 1}
              onclick={() => viewingPage++}
            >›</button>
          {/if}
          <button class="btn btn-danger btn-sm" onclick={() => deleteDoc(viewingDoc!.id)}>🗑</button>
          <button class="btn btn-secondary btn-sm" onclick={() => (viewingDoc = null)}>✕</button>
        </div>
      </div>
      <div class="doc-modal-body">
        <img
          src={tripDocumentsApi.viewUrl(viewingDoc.id, viewingPage)}
          alt={viewingDoc.filename}
          class="doc-modal-img"
        />
      </div>
    </div>
  </div>
{/if}
