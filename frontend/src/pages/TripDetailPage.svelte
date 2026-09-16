<script lang="ts">
  import { tick } from "svelte";
  import { location } from "svelte-spa-router";
  import {
    tripsApi,
    settingsApi,
    tripDocumentsApi,
    sharesApi,
    boardingPassesApi,
  } from "../api/client";
  import TripBudget from "../components/TripBudget.svelte";
  import TripExpenses from "../components/TripExpenses.svelte";
  import TripPackingList from "../components/TripPackingList.svelte";
  import TripTransport from "../components/TripTransport.svelte";
  import TripStays from "../components/TripStays.svelte";
  import TripPeople from "../components/TripPeople.svelte";
  import TripCarRentals from "../components/TripCarRentals.svelte";
  import { tripImageBust } from "../lib/tripImageStore";
  import type {
    Trip,
    Flight,
    TripDocument,
    TripShare,
    TripBoardingPass,
    TripSegment,
    TripStay,
    TripCarRental,
    // Aliased: `TripBudget` is the component imported above.
    TripBudget as TripBudgetStatus,
  } from "../api/types";
  import {
    budgetLevel,
    formatCurrencyTotals,
    formatDateRange,
    inferTripStatus,
    timeUntilTrip,
    tripContents,
    tripPeople,
  } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import ImmichAlbumButton from "../components/ImmichAlbumButton.svelte";
  import TripMap from "../components/TripMap.svelte";
  import TripDayPlanner from "../components/TripDayPlanner.svelte";
  import ConfirmModal from "../components/ConfirmModal.svelte";
  import { t } from "../lib/i18n";

  interface Props {
    params: { id: string };
  }
  const { params }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let trip = $state<Trip | null>(null);
  let immichConfigured = $state(false);
  let immichBaseUrl = $state("");
  let defaultCurrency = $state("EUR");

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
      immichBaseUrl = s?.immich_url?.replace(/\/$/, "") ?? "";
      defaultCurrency = s?.default_currency ?? "EUR";
      // If an album ID is stored, verify it still exists in Immich
      if (trip.immich_album_id && immichConfigured) {
        const status = await tripsApi
          .checkImmichAlbum(params.id)
          .catch(() => null);
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

  const fromHistory = $derived($location.startsWith("/history"));
  const backUrl = $derived(fromHistory ? "#/history" : "#/trips");
  const flightBasePath = $derived(fromHistory ? "history" : "trips");

  const flightList = $derived<Flight[]>(trip?.flights ?? []);
  const dateRange = $derived(formatDateRange(trip?.start_date, trip?.end_date));

  const airlines = $derived([
    ...new Set(flightList.map((f) => f.airline_code).filter(Boolean)),
  ]);

  // ---- Destination image ----
  let refreshingImage = $state(false);
  let imageRetried = false;

  async function handleImageError(e: Event) {
    const cover = (e.currentTarget as HTMLElement).closest(
      ".trip-detail-cover",
    ) as HTMLElement;
    if (imageRetried) {
      cover.style.display = "none";
      return;
    }
    imageRetried = true;
    try {
      await tripsApi.refreshImage(params.id);
      tripImageBust.bust(params.id);
    } catch {
      cover.style.display = "none";
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

  const isCompleted = $derived(
    trip ? inferTripStatus(trip) === "completed" : false,
  );

  // ---- Rating ----
  let hoverRating = $state<number | null>(null);
  let touchSliding = $state(false);

  async function setRating(star: number | null) {
    if (!trip) return;
    const newRating = star === null || trip.rating === star ? null : star;
    const id = trip.id;
    trip = { ...trip, rating: newRating };
    await tripsApi.setRating(id, newRating);
  }

  function ratingFromTouch(e: TouchEvent, el: HTMLElement): number {
    const rect = el.getBoundingClientRect();
    const x = e.touches[0].clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, x / rect.width));
    return Math.max(0.5, Math.min(5, Math.round(ratio * 10) / 2));
  }

  function onRatingTouchStart(e: TouchEvent) {
    touchSliding = true;
    hoverRating = ratingFromTouch(e, e.currentTarget as HTMLElement);
  }

  function onRatingTouchMove(e: TouchEvent) {
    if (!touchSliding) return;
    e.preventDefault();
    hoverRating = ratingFromTouch(e, e.currentTarget as HTMLElement);
  }

  function onRatingTouchEnd() {
    if (!touchSliding) return;
    touchSliding = false;
    setRating(hoverRating);
    hoverRating = null;
  }

  // ---- Shared note ----
  let noteSaving = $state(false);
  let noteSaved = $state(false);
  let noteTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleNoteSave(value: string) {
    if (!trip) return;
    trip = { ...trip, note: value };
    if (noteTimer) clearTimeout(noteTimer);
    noteTimer = setTimeout(async () => {
      noteSaving = true;
      await tripsApi.setNote(trip!.id, value || null);
      noteSaving = false;
      noteSaved = true;
      setTimeout(() => {
        noteSaved = false;
      }, 2000);
    }, 800);
  }

  // ---- Ground transport ----
  // Held here rather than only inside TripSegments so the map can draw the
  // ground legs alongside the flight arcs.
  let segments = $state<TripSegment[]>([]);
  let stays = $state<TripStay[]>([]);
  /* Reported by the section below so the header's inventory line and the day
   * planner both see the rentals without a second fetch — the same contract
   * `stays` has. */
  let carRentals = $state<TripCarRental[]>([]);
  /* What the trip actually holds, next to its dates. The card carries a coarser
   * version — it only has per-kind counts, so a mixed trip there says "3 legs".
   * Here the rows are loaded, so each kind can be named. */
  const contents = $derived(
    tripContents(
      flightList.length,
      segments.map((s) => s.type),
      stays.length,
      carRentals.length,
    ),
  );

  function plural(key: string, n: number): string {
    return $t(n === 1 ? key : `${key}_plural`, { values: { n } });
  }

  /* Who else is on the trip. Read off the trip payload rather than the
   * collaborators list loaded below, because `GET /api/trips/{id}/shares` is
   * owner-only — a collaborator's copy of that list is always empty, and the
   * header would tell them they are travelling alone. Rendered in the same
   * shape as `contents` so the two share one row and one separator rule. */
  const peopleParts = $derived.by(() => {
    const people = tripPeople(
      trip?.collaborator_count ?? 0,
      trip?.pending_invite_count ?? 0,
      // The live roster, reported by the People section — so adding a guest
      // updates the header without a refetch. Seeded from the trip payload so
      // the count is right on first paint, before that section has loaded.
      tripGuestCount ?? trip?.guest_count ?? 0,
    );
    if (!people) return [];
    const parts = [
      { icon: "👥", labelKey: "trips.people_count", count: people.people },
    ];
    if (people.pending > 0) {
      parts.push({
        icon: "✉",
        labelKey: "trips.pending_invite_count",
        count: people.pending,
      });
    }
    return parts;
  });

  /* Seeded from the trip payload so the line is right on first paint, then kept
   * current by the expenses section — which is the only thing that knows an
   * expense was just added. */
  let expenseTotals = $state<Record<string, number> | undefined>(undefined);
  let budgetPanel = $state<{ reload: () => void } | null>(null);

  /* The budget, reported by the panel below so the header does not fetch it a
   * second time. Shown as its own chip rather than folded into the expense
   * totals beside it: those are the *trip's* spend per currency, this is the
   * share of whoever the budget belongs to against **their** limit — two
   * different figures that would be a lie if added together. */
  let budgetStatus = $state<TripBudgetStatus | null>(null);
  const budgetChip = $derived.by(() => {
    const amount = budgetStatus?.amount;
    const currency = budgetStatus?.currency;
    if (amount == null || currency == null) return null;
    const spent = budgetStatus!.spent;
    return {
      level: budgetLevel(spent, amount),
      label: `${formatCurrencyTotals({ [currency]: spent })[0]} / ${formatCurrencyTotals({ [currency]: amount })[0]}`,
    };
  });
  /* A budget naming more than one person measures their combined share, not
   * yours, so the sentence under the panel and the chip's tooltip both have to
   * say so. */
  const budgetIsShared = $derived((budgetStatus?.members?.length ?? 0) > 1);
  const expenseLabels = $derived(
    formatCurrencyTotals(expenseTotals ?? trip?.expenses_total),
  );

  // ---- Documents ----
  let documents = $state<TripDocument[]>([]);
  let tripBoardingPasses = $state<TripBoardingPass[]>([]);
  let docUploading = $state(false);
  let docUploadError = $state<string | null>(null);
  const docsEmpty = $derived(
    documents.length === 0 && tripBoardingPasses.length === 0,
  );
  let viewingDoc = $state<TripDocument | null>(null);
  let viewingBp = $state<TripBoardingPass | null>(null);
  let viewingPage = $state(0);

  async function loadDocuments() {
    if (!trip) return;
    [documents, tripBoardingPasses] = await Promise.all([
      tripDocumentsApi.list(trip.id).catch(() => []),
      boardingPassesApi.listForTrip(trip.id).catch(() => []),
    ]);
  }

  async function handleDocUpload(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file || !trip) return;
    (e.currentTarget as HTMLInputElement).value = "";
    docUploading = true;
    docUploadError = null;
    try {
      await tripDocumentsApi.upload(trip.id, file);
      await loadDocuments();
    } catch (err) {
      docUploadError = (err as Error).message || $t("trip.doc_upload_error");
    } finally {
      docUploading = false;
    }
  }

  async function deleteDoc(docId: string) {
    if (!confirm($t("trip.doc_delete_confirm"))) return;
    await tripDocumentsApi.delete(docId);
    documents = documents.filter((d) => d.id !== docId);
    if (viewingDoc?.id === docId) viewingDoc = null;
  }

  async function deleteTripBp(bpId: string) {
    if (!confirm($t("trip.doc_delete_confirm"))) return;
    await boardingPassesApi.delete(bpId);
    tripBoardingPasses = tripBoardingPasses.filter((b) => b.id !== bpId);
    if (viewingBp?.id === bpId) viewingBp = null;
  }

  // ---- Delete trip ----
  let showDeleteConfirm = $state(false);
  let deleting = $state(false);

  async function confirmDeleteTrip() {
    if (!trip) return;
    deleting = true;
    try {
      await tripsApi.delete(trip.id);
      window.location.hash = "/";
    } catch (err) {
      alert((err as Error).message);
    } finally {
      deleting = false;
      showDeleteConfirm = false;
    }
  }

  // ---- Merge trip ----
  let showMergeModal = $state(false);
  let mergeTrips = $state<Trip[]>([]);
  let mergeTargetId = $state("");
  let mergeError = $state<string | null>(null);
  let merging = $state(false);
  let mergeLoading = $state(false);

  async function openMergeModal() {
    showMergeModal = true;
    mergeError = null;
    mergeTargetId = "";
    mergeLoading = true;
    try {
      const res = await tripsApi.list();
      mergeTrips = res.trips.filter(
        (t) => t.id !== trip?.id && t.is_owner !== false,
      );
    } catch (err) {
      mergeError = (err as Error).message;
    } finally {
      mergeLoading = false;
    }
  }

  async function confirmMerge() {
    if (!trip || !mergeTargetId) return;
    merging = true;
    mergeError = null;
    try {
      const result = await tripsApi.merge(trip.id, mergeTargetId);
      showMergeModal = false;
      window.location.hash = `/trips/${result.target_trip_id}`;
    } catch (err) {
      mergeError = (err as Error).message;
    } finally {
      merging = false;
    }
  }

  // ---- Share trip ----
  let showSharePanel = $state(false);
  let shareUsername = $state("");
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
      shareUsername = "";
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

  // ---- Collapsible sections ----
  let flightsCollapsed = $state(false);
  let staysCollapsed = $state(false);
  let peopleCollapsed = $state(false);
  /* The trip's guest roster size, reported by the People section so the
   * header's companion count stays live without re-fetching the trip. Null
   * until that section reports, so the header falls back to the trip payload's
   * own figure and does not flash a zero on first paint. */
  let tripGuestCount = $state<number | null>(null);
  let carRentalsCollapsed = $state(false);
  let plannerCollapsed = $state(false);
  let packingCollapsed = $state(false);
  let printing = $state(false);

  async function exportPdf() {
    const prevFlights = flightsCollapsed;
    const prevStays = staysCollapsed;
    const prevPlanner = plannerCollapsed;
    flightsCollapsed = false;
    staysCollapsed = false;
    plannerCollapsed = false;
    printing = true;
    await tick();
    // Two animation frames ensure the browser has fully painted before the print dialog opens
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    window.print();
    printing = false;
    flightsCollapsed = prevFlights;
    staysCollapsed = prevStays;
    plannerCollapsed = prevPlanner;
  }

  // plannerContent removed — section header no longer shows a summary

  function todayStr(): string {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }

  // The day the planner should highlight when collapsed
  const plannerFocusDate = $derived(
    (() => {
      if (!trip || !trip.start_date || !trip.end_date) return null;
      const status = inferTripStatus(trip);
      if (status === "upcoming") return trip.start_date;
      if (status === "completed") return trip.end_date;
      const today = todayStr();
      if (today >= trip.start_date && today <= trip.end_date) return today;
      return trip.start_date;
    })(),
  );

  // Flights collapsed summary
  const flightsSummary = $derived(
    (() => {
      if (!trip || flightList.length === 0) return null;
      const status = inferTripStatus(trip);
      const now = Date.now();

      if (status === "completed") {
        // Route: GRU → CDG → LHR · N flights
        const airports: string[] = [];
        for (const f of flightList) {
          if (airports[airports.length - 1] !== f.departure_airport)
            airports.push(f.departure_airport);
          if (airports[airports.length - 1] !== f.arrival_airport)
            airports.push(f.arrival_airport);
        }
        const route = airports.join(" → ");
        const n = flightList.length;
        return `${route} · ${n} ${n === 1 ? $t("trips.flight_count", { values: { n } }) : $t("trips.flight_count_plural", { values: { n } })}`;
      }

      // Upcoming or active — find next relevant flight
      const sorted = [...flightList].sort(
        (a, b) =>
          new Date(a.departure_datetime ?? 0).getTime() -
          new Date(b.departure_datetime ?? 0).getTime(),
      );

      // Currently in the air?
      const inAir = sorted.find(
        (f) =>
          f.departure_datetime &&
          f.arrival_datetime &&
          new Date(f.departure_datetime).getTime() <= now &&
          new Date(f.arrival_datetime).getTime() > now,
      );
      if (inAir)
        return `✈ ${inAir.flight_number}  ${inAir.departure_airport} → ${inAir.arrival_airport}`;

      // Next to depart
      const next = sorted.find(
        (f) =>
          f.departure_datetime &&
          new Date(f.departure_datetime).getTime() > now,
      );
      if (next) {
        const countdown = next.departure_datetime
          ? timeUntilTrip(next.departure_datetime, now, $t)
          : "";
        return `${$t("trip.next_flight")}: ${next.flight_number}  ${next.departure_airport} → ${next.arrival_airport}${countdown ? "  " + countdown : ""}`;
      }

      return null;
    })(),
  );

  // ---- Leave shared trip (non-owner) ----
  let leaving = $state(false);

  async function leaveTrip() {
    if (!trip || !confirm($t("trip.leave_confirm"))) return;
    leaving = true;
    try {
      await sharesApi.leaveTrip(trip.id);
      window.location.hash = "/trips";
    } catch (err) {
      alert((err as Error).message);
    } finally {
      leaving = false;
    }
  }

  /* Loaded with the trip, not when the share panel is opened.
   *
   * This was lazy while the share panel was the only thing that read it. The
   * People section lists collaborators and outstanding invitations too, so
   * deferring the fetch left that section showing just the owner and the guests
   * until you happened to click Share — at which point the names appeared, which
   * reads as a bug rather than as lazy loading.
   *
   * `loadCollaborators` returns early for a non-owner (the endpoint is
   * owner-only), so this costs a collaborator nothing and TripPeople already
   * renders correctly against the empty list it gets. */
  $effect(() => {
    if (trip?.id) {
      loadCollaborators();
    }
  });
</script>

<TopNav
  title={loading ? $t("trip.loading") : (trip?.name ?? "Error")}
  backHref={backUrl}
/>

<div class="main-content trip-page">
  {#if loading}
    <LoadingScreen message={$t("trip.loading")} />
  {:else if error}
    <EmptyState icon="⚠️" title={$t("trip.load_error")} description={error}>
      <a href="#/trips" class="btn btn-primary">{$t("trip.back")}</a>
    </EmptyState>
  {:else if trip}
    <!-- Trip Header -->
    <div class="trip-header">
      <div class="trip-detail-cover" style="display:none">
        <img
          src={tripImageBust.urlFor(trip.id, $tripImageBust)}
          alt=""
          class="trip-detail-cover-img"
          onload={(e) => {
            (
              (e.currentTarget as HTMLElement).closest(
                ".trip-detail-cover",
              ) as HTMLElement
            ).style.display = "";
          }}
          onerror={(e) => handleImageError(e)}
        />
        <button
          class="trip-card-img-refresh"
          title={$t("trips.refresh_image")}
          aria-label={$t("trips.refresh_image")}
          disabled={refreshingImage}
          onclick={refreshImage}
        >
          {refreshingImage ? "…" : "↻"}
        </button>
      </div>
      <div class="trip-header-route">{trip.name}</div>
      {#if dateRange}
        <div class="trip-header-dates">
          <span>📅 {dateRange}</span>
        </div>
      {/if}
      {#if contents.length > 0 || peopleParts.length > 0 || expenseLabels.length > 0}
        <p class="trip-header-contents">
          {#each contents as part, i (part.labelKey)}
            {#if i > 0}<span class="trip-header-sep" aria-hidden="true">·</span>{/if}
            <span>{part.icon} {plural(part.labelKey, part.count)}</span>
          {/each}
          {#each peopleParts as part, i (part.labelKey)}
            {#if contents.length > 0 || i > 0}
              <span class="trip-header-sep" aria-hidden="true">·</span>
            {/if}
            <span>{part.icon} {plural(part.labelKey, part.count)}</span>
          {/each}
          {#each expenseLabels as label (label)}
            <span class="trip-header-sep" aria-hidden="true">·</span>
            <span>💰 {label}</span>
          {/each}
          {#if budgetChip}
            <span class="trip-header-sep" aria-hidden="true">·</span>
            <span
              class="trip-header-budget"
              data-level={budgetChip.level}
              title={$t(budgetIsShared ? 'budget.hint_shared' : 'budget.hint')}
            >
              🎯 {budgetChip.label}
            </span>
          {/if}
        </p>
      {/if}
      <div
        style="margin-top:var(--space-sm);display:flex;gap:var(--space-xs);flex-wrap:wrap"
      >
        {#each airlines as airline}
          <span class="airline-badge airline-{airline}">{airline}</span>
        {/each}
        {#each trip.booking_refs ?? [] as ref}
          <span class="text-sm text-muted">Ref: {ref}</span>
        {/each}
      </div>
      {#if trip.is_owner === false && trip.owner_username}
        <div
          style="margin-top:var(--space-sm);font-size:0.8rem;color:var(--text-muted)"
        >
          {$t("trip.shared_by")}
          {trip.owner_username}
        </div>
      {/if}
      <div
        class="trip-actions"
        style="margin-top:var(--space-md);display:flex;gap:var(--space-sm);flex-wrap:wrap;align-items:center"
      >
        {#if trip.is_owner !== false}
          <a
            href="#/trips/{params.id}/edit"
            class="btn btn-secondary"
            style="font-size:0.85rem"
          >
            ✎ {$t("trip.edit")}
          </a>
        {/if}
        {#if flightList.length > 0}
          <a
            href="/api/trips/{params.id}/ical"
            download="{trip.name || 'trip'}.ics"
            class="btn btn-secondary no-print"
            style="font-size:0.85rem"
          >
            📅 {$t("trip.export_ical")}
          </a>
          <button
            class="btn btn-secondary no-print"
            style="font-size:0.85rem"
            onclick={exportPdf}
          >
            🖨 {$t("trip.export_pdf")}
          </button>
        {/if}
        {#if isCompleted && immichConfigured}
          <ImmichAlbumButton
            tripId={trip.id}
            immichAlbumId={trip.immich_album_id}
            {immichBaseUrl}
            style="display:inline-flex;align-items:center;gap:var(--space-xs);font-size:0.85rem"
            onAlbumCreated={(albumId) => {
              trip = { ...trip!, immich_album_id: albumId };
            }}
          />
        {/if}
        {#if trip.is_owner !== false}
          <button
            class="btn btn-secondary"
            style="font-size:0.85rem"
            onclick={() => {
              showSharePanel = !showSharePanel;
            }}
          >
            ⤷ {$t("trip.share")}
          </button>
          <button
            class="btn btn-secondary"
            style="font-size:0.85rem"
            onclick={openMergeModal}
          >
            ⇄ {$t("trip.merge")}
          </button>
          <button
            class="btn btn-danger"
            style="font-size:0.85rem"
            disabled={deleting}
            onclick={() => (showDeleteConfirm = true)}
          >
            🗑 {$t("trip.delete")}
          </button>
        {:else}
          <button
            class="btn btn-secondary"
            style="font-size:0.85rem"
            disabled={leaving}
            onclick={leaveTrip}
          >
            ✕ {$t("trip.leave")}
          </button>
        {/if}
      </div>

      {#if showSharePanel && trip.is_owner !== false}
        <div class="share-panel no-print" style="margin-top:var(--space-md)">
          <h4 style="margin:0 0 var(--space-sm)">{$t("trip.collaborators")}</h4>
          <div
            style="display:flex;gap:var(--space-xs);margin-bottom:var(--space-sm)"
          >
            <input
              type="text"
              class="form-input"
              placeholder={$t("trip.share_username_placeholder")}
              bind:value={shareUsername}
              oninput={() => {
                shareSuccess = null;
                shareError = null;
              }}
              style="flex:1;min-width:0"
            />
            <button
              class="btn btn-primary btn-sm"
              disabled={sharing || !shareUsername.trim()}
              onclick={handleShare}
            >
              {sharing ? "…" : $t("trip.share_invite")}
            </button>
          </div>
          {#if shareError}
            <p
              style="color:var(--danger);font-size:0.85rem;margin:var(--space-xs) 0 0"
            >
              {shareError}
            </p>
          {/if}
          {#if shareSuccess}
            <p
              style="color:var(--success);font-size:0.85rem;margin:var(--space-xs) 0 0"
            >
              ✓ {shareSuccess}
            </p>
          {/if}
          {#if collaborators.length > 0}
            <ul style="list-style:none;padding:0;margin:0">
              {#each collaborators as collab (collab.user_id)}
                <li
                  style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-xs) 0;gap:var(--space-sm)"
                >
                  <span
                    style="display:flex;align-items:center;gap:var(--space-xs)"
                  >
                    {collab.username}
                    <span
                      style="font-size:0.75rem;padding:2px 6px;border-radius:10px;background:var(--{collab.status ===
                      'accepted'
                        ? 'success'
                        : 'warning'}-bg, {collab.status === 'accepted'
                        ? '#d1fae5'
                        : '#fef3c7'});color:{collab.status === 'accepted'
                        ? 'var(--success, #065f46)'
                        : 'var(--warning-text, #92400e)'}"
                    >
                      {$t(`trip.share_status_${collab.status}`)}
                    </span>
                  </span>
                  <button
                    class="btn btn-danger btn-sm"
                    onclick={() => revokeCollaborator(collab.user_id)}
                  >
                    {$t("trip.revoke_access")}
                  </button>
                </li>
              {/each}
            </ul>
          {:else}
            <p style="font-size:0.85rem;color:var(--text-muted)">
              No collaborators yet.
            </p>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Route Map -->
    {#if flightList.length > 0 || segments.length > 0}
      <TripMap flights={flightList} {segments} />
    {/if}

    {#if flightList.length === 0 && segments.length === 0 && stays.length === 0}
      <EmptyState title={$t("trip.empty")}>
        <a href="#/trips/{params.id}/add-transport" class="btn btn-primary"
          >{$t("trip.add_transport")}</a
        >
      </EmptyState>
    {/if}

    <!-- The itinerary spine: how you move, where you sleep, what each day holds.
         Its own flow, so a short section next to it never opens a row-band hole. -->
    <div class="trip-spine">
      <!-- Transport: flights and ground legs in one list -->
      <div class="trip-section">
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="trip-section-header section-toggle"
          class:no-bottom-margin={flightsCollapsed}
          onclick={() => (flightsCollapsed = !flightsCollapsed)}
        >
          <div class="section-header-inner">
            <div class="section-title-row">
              <h3 class="trip-section-title">{$t("trip.transport")}</h3>
              <span class="section-chevron">{flightsCollapsed ? "▼" : "▲"}</span
              >
            </div>
            {#if flightsCollapsed && flightsSummary}
              <p class="section-summary">{flightsSummary}</p>
            {/if}
          </div>
        </div>
        <div class:section-hidden={flightsCollapsed}>
          <TripTransport
            {trip}
            flights={flightList}
            {flightBasePath}
            onchange={(list) => (segments = list)}
          />
        </div>
      </div>

      <!-- Stays: accommodation for the trip -->
      <div class="trip-section">
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="trip-section-header section-toggle"
          onclick={() => (staysCollapsed = !staysCollapsed)}
        >
          <div class="section-header-inner">
            <div class="section-title-row">
              <h3 class="trip-section-title">{$t("stays.title")}</h3>
              <span class="section-chevron">{staysCollapsed ? "▼" : "▲"}</span>
            </div>
          </div>
        </div>
        <div class:section-hidden={staysCollapsed}>
          <TripStays
            {trip}
            flights={flightList}
            {segments}
            onchange={(list) => (stays = list)}
          />
        </div>
      </div>

      <!-- People: who is on the trip. Its guest roster is what bounds the
           expense payer/split pickers, so it sits with the trip's contents
           rather than inside Expenses — a companion is a fact about the trip,
           not about its bills. -->
      <div class="trip-section">
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="trip-section-header section-toggle"
          onclick={() => (peopleCollapsed = !peopleCollapsed)}
        >
          <div class="section-header-inner">
            <div class="section-title-row">
              <h3 class="trip-section-title">{$t("trip_people.title")}</h3>
              <span class="section-chevron">{peopleCollapsed ? "▼" : "▲"}</span>
            </div>
          </div>
        </div>
        <div class:section-hidden={peopleCollapsed}>
          <TripPeople
            {trip}
            {collaborators}
            onchange={(list) => (tripGuestCount = list.length)}
          />
        </div>
      </div>

      <!-- Car rental: the hired vehicle, not the drives taken in it. Sits after
           Stays and before the planner, continuing the section order — how you
           move, where you sleep, what you drove, what you did each day. -->
      <div class="trip-section">
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="trip-section-header section-toggle"
          onclick={() => (carRentalsCollapsed = !carRentalsCollapsed)}
        >
          <div class="section-header-inner">
            <div class="section-title-row">
              <h3 class="trip-section-title">{$t("car_rentals.title")}</h3>
              <span class="section-chevron">{carRentalsCollapsed ? "▼" : "▲"}</span>
            </div>
          </div>
        </div>
        <div class:section-hidden={carRentalsCollapsed}>
          <TripCarRentals {trip} onchange={(list) => (carRentals = list)} />
        </div>
      </div>

      <!-- Day Planner -->
      {#if trip.start_date && trip.end_date}
        <div class="trip-section">
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="trip-section-header section-toggle"
            onclick={() => (plannerCollapsed = !plannerCollapsed)}
          >
            <div class="section-header-inner">
              <div class="section-title-row">
                <h3 class="trip-section-title">{$t("planner.title")}</h3>
                <span class="section-chevron"
                  >{plannerCollapsed ? "▼" : "▲"}</span
                >
              </div>
            </div>
          </div>
          <TripDayPlanner
            {segments}
            {stays}
            {carRentals}
            {trip}
            forceExpanded={printing}
            onlyDate={plannerCollapsed
              ? (plannerFocusDate ?? undefined)
              : undefined}
            collapseAll={plannerCollapsed}
          />
        </div>
      {/if}

      <!-- Documents -->
      <div
        class="trip-section trip-section-documents no-print"
        class:trip-section-compact={docsEmpty && !docUploadError}
      >
        <div class="trip-section-header" class:header-with-note={docsEmpty}>
          <h3 class="trip-section-title">{$t("trip.documents")}</h3>
          {#if docsEmpty}
            <span class="section-note">{$t("trip.doc_empty")}</span>
          {/if}
          <label class="btn btn-secondary btn-sm" class:disabled={docUploading}>
            {docUploading ? $t("trip.doc_uploading") : $t("trip.doc_add")}
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
        {#if !docsEmpty}
          <div class="doc-grid">
            {#each tripBoardingPasses as bp (bp.id)}
              <button
                class="doc-thumb"
                onclick={() => {
                  viewingBp = bp;
                  viewingDoc = null;
                }}
              >
                <img
                  src={boardingPassesApi.imageUrl(bp.id)}
                  alt={bp.flight_number ?? "Boarding pass"}
                  loading="lazy"
                />
                <span class="doc-thumb-name"
                  >🎫 {bp.flight_number}
                  {bp.departure_airport}→{bp.arrival_airport}</span
                >
              </button>
            {/each}
            {#each documents as doc (doc.id)}
              <button
                class="doc-thumb"
                onclick={() => {
                  viewingDoc = doc;
                  viewingBp = null;
                  viewingPage = 0;
                }}
              >
                <img
                  src={tripDocumentsApi.viewUrl(doc.id)}
                  alt={doc.filename}
                  loading="lazy"
                />
                <span class="doc-thumb-name">{doc.filename}</span>
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    <!-- The trip's desk: short, ancillary cards, stacked in a narrow column. -->
    <div class="trip-aside">
      <!-- Packing List -->
      <div class="trip-section no-print">
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="trip-section-header section-toggle"
          onclick={() => (packingCollapsed = !packingCollapsed)}
        >
          <div class="section-header-inner">
            <div class="section-title-row">
              <h3 class="trip-section-title">{$t("packing.title")}</h3>
              <span class="section-chevron">{packingCollapsed ? "▼" : "▲"}</span
              >
            </div>
          </div>
        </div>
        <div class:section-hidden={packingCollapsed}>
          <TripPackingList tripId={params.id} />
        </div>
      </div>

      <!-- Expenses -->
      <div class="trip-section no-print">
        <div class="trip-section-header">
          <h3 class="trip-section-title">{$t("expenses.title")}</h3>
        </div>
        <!-- The budget reads its spend from the same expenses listed below, so a
             new expense has to nudge it — see `TripBudget.reload` for why this
             is a call rather than a prop the list can bump. -->
        <TripBudget
          bind:this={budgetPanel}
          tripId={params.id}
          {defaultCurrency}
          onchange={(status) => (budgetStatus = status)}
        />
        <!-- A shared budget counts more than your own share, so the sentence
             explaining what the bar measures has to change with it. -->
        <p class="form-hint budget-hint">{$t(budgetIsShared ? 'budget.hint_shared' : 'budget.hint')}</p>

        <TripExpenses
          tripId={params.id}
          {defaultCurrency}
          onchange={(totals) => {
            expenseTotals = totals;
            budgetPanel?.reload();
          }}
        />
      </div>

      <!-- Shared note -->
      <div class="trip-section trip-section-tail no-print">
        <div class="trip-section-header">
          <h3 class="trip-section-title">{$t("trips.note_label")}</h3>
          {#if noteSaving}
            <span class="note-status">…</span>
          {:else if noteSaved}
            <span class="note-status note-status-ok"
              >✓ {$t("trips.note_saved")}</span
            >
          {/if}
        </div>
        <textarea
          class="trip-note-textarea"
          placeholder={$t("trips.note_placeholder")}
          value={trip.note ?? ""}
          oninput={(e) =>
            scheduleNoteSave((e.currentTarget as HTMLTextAreaElement).value)}
          rows={4}
        ></textarea>
      </div>

      <!-- Rating -->
      <div class="trip-section trip-section-compact trip-section-tail no-print">
        <!-- Stars ride on the header row: five glyphs and a title are one line's
           worth of content, and a card of their own was mostly padding. -->
        <div class="trip-section-header rating-header">
          <h3 class="trip-section-title">{$t("trips.rating_label")}</h3>
          <div class="rating-header-actions">
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <div
              class="trip-rating-stars"
              role="group"
              ontouchstart={onRatingTouchStart}
              ontouchmove={onRatingTouchMove}
              ontouchend={onRatingTouchEnd}
              onpointerleave={(e) => {
                if (e.pointerType === "mouse") hoverRating = null;
              }}
            >
              {#each [1, 2, 3, 4, 5] as star}
                {@const displayRating = hoverRating ?? trip.rating ?? 0}
                <span class="rating-star-wrap">
                  <!-- left half = star - 0.5, right half = star -->
                  <button
                    class="rating-half left"
                    onpointerenter={(e) => {
                      if (e.pointerType === "mouse") hoverRating = star - 0.5;
                    }}
                    onclick={() => setRating(star - 0.5)}
                    aria-label="Rate {star - 0.5} out of 5"
                  ></button>
                  <button
                    class="rating-half right"
                    onpointerenter={(e) => {
                      if (e.pointerType === "mouse") hoverRating = star;
                    }}
                    onclick={() => setRating(star)}
                    aria-label="Rate {star} out of 5"
                  ></button>
                  <span
                    class="rating-star-glyph"
                    style="--fill: {displayRating >= star
                      ? '100%'
                      : displayRating >= star - 0.5
                        ? '50%'
                        : '0%'}"
                    aria-hidden="true"
                  ></span>
                </span>
              {/each}
            </div>
            {#if trip.rating}
              <button
                class="btn btn-secondary btn-sm"
                onclick={() => setRating(null)}
              >
                {$t("trips.rating_clear")}
              </button>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

{#if showDeleteConfirm}
  <ConfirmModal
    message={$t("trip.delete_confirm")}
    confirmLabel={$t("trip.delete")}
    cancelLabel="Cancel"
    danger={true}
    onConfirm={confirmDeleteTrip}
    onCancel={() => (showDeleteConfirm = false)}
  />
{/if}

{#if showMergeModal}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    role="presentation"
    style="position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:200;padding:var(--space-md)"
    onclick={() => (showMergeModal = false)}
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      role="dialog"
      aria-modal="true"
      tabindex="-1"
      style="background:var(--bg-card);border-radius:var(--radius-md);padding:var(--space-lg);max-width:420px;width:100%;box-shadow:var(--shadow-lg)"
      onclick={(e) => e.stopPropagation()}
    >
      <h3 style="margin:0 0 var(--space-sm);font-size:1rem">
        {$t("trip.merge_title")}
      </h3>
      <p
        style="margin:0 0 var(--space-md);font-size:0.875rem;color:var(--text-muted)"
      >
        {$t("trip.merge_description")}
      </p>
      {#if mergeLoading}
        <p style="font-size:0.875rem;color:var(--text-muted)">
          {$t("trip.merge_loading")}
        </p>
      {:else if mergeTrips.length === 0}
        <p style="font-size:0.875rem;color:var(--text-muted)">
          {$t("trip.merge_no_trips")}
        </p>
      {:else}
        <select
          class="form-input"
          style="width:100%;margin-bottom:var(--space-md)"
          bind:value={mergeTargetId}
        >
          <option value="">{$t("trip.merge_select_placeholder")}</option>
          {#each mergeTrips as t (t.id)}
            <option value={t.id}>{t.name}</option>
          {/each}
        </select>
      {/if}
      {#if mergeError}
        <p
          style="color:var(--danger);font-size:0.85rem;margin:0 0 var(--space-sm)"
        >
          {mergeError}
        </p>
      {/if}
      <div
        style="display:flex;gap:var(--space-sm);justify-content:flex-end;margin-top:var(--space-md)"
      >
        <button
          class="btn btn-secondary"
          onclick={() => (showMergeModal = false)}
        >
          {$t("trip.merge_cancel")}
        </button>
        <button
          class="btn btn-primary"
          disabled={!mergeTargetId || merging}
          onclick={confirmMerge}
        >
          {merging ? $t("trip.merge_merging") : $t("trip.merge_confirm")}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Document viewer modal -->
{#if viewingDoc}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="doc-modal-overlay"
    role="presentation"
    onclick={() => (viewingDoc = null)}
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="doc-modal"
      role="dialog"
      aria-modal="true"
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
    >
      <div class="doc-modal-header">
        <span class="doc-modal-name">{viewingDoc.filename}</span>
        <div class="doc-modal-actions">
          {#if viewingDoc.page_count > 1}
            <button
              class="btn btn-secondary btn-sm"
              disabled={viewingPage === 0}
              onclick={() => viewingPage--}>‹</button
            >
            <span class="doc-page-label">
              {$t("trip.doc_page", {
                values: {
                  current: viewingPage + 1,
                  total: viewingDoc.page_count,
                },
              })}
            </span>
            <button
              class="btn btn-secondary btn-sm"
              disabled={viewingPage >= viewingDoc.page_count - 1}
              onclick={() => viewingPage++}>›</button
            >
          {/if}
          <button
            class="btn btn-danger btn-sm"
            onclick={() => deleteDoc(viewingDoc!.id)}>🗑</button
          >
          <button
            class="btn btn-secondary btn-sm"
            onclick={() => (viewingDoc = null)}>✕</button
          >
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

<!-- Boarding pass viewer modal -->
{#if viewingBp}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="doc-modal-overlay"
    role="presentation"
    onclick={() => (viewingBp = null)}
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="doc-modal"
      role="dialog"
      aria-modal="true"
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
    >
      <div class="doc-modal-header">
        <span class="doc-modal-name">
          🎫 {viewingBp.flight_number}
          {viewingBp.departure_airport}→{viewingBp.arrival_airport}
          {#if viewingBp.passenger_name}<span
              style="font-weight:normal;font-size:0.85rem"
            >
              · {viewingBp.passenger_name}</span
            >{/if}
          {#if viewingBp.seat}<span
              style="font-weight:normal;font-size:0.85rem"
            >
              · {$t("flight.seat")} {viewingBp.seat}</span
            >{/if}
        </span>
        <div class="doc-modal-actions">
          {#if trip?.is_owner !== false}
            <button
              class="btn btn-danger btn-sm"
              onclick={() => deleteTripBp(viewingBp!.id)}>🗑</button
            >
          {/if}
          <button
            class="btn btn-secondary btn-sm"
            onclick={() => (viewingBp = null)}>✕</button
          >
        </div>
      </div>
      <div class="doc-modal-body">
        <img
          src={boardingPassesApi.imageUrl(viewingBp.id)}
          alt="Boarding pass"
          class="doc-modal-img"
        />
      </div>
    </div>
  </div>
{/if}
