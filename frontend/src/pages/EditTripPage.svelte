<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { tripsApi, segmentsApi, staysApi, airportsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import FormSection from '../components/FormSection.svelte';
  import PlaceInput from '../components/PlaceInput.svelte';
  import type { PickedPlace, Trip } from '../api/types';
  import { localDateKey } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    params: { id: string };
  }
  const { params }: Props = $props();

  const backUrl = $derived(`#/trips/${params.id}`);

  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let submitting = $state(false);
  let error = $state<string | null>(null);

  let name = $state('');
  let startDate = $state('');
  let endDate = $state('');

  /** The trip's typed ends — see AddTripPage for why they are their own columns. */
  const emptyPlace = (): PickedPlace => ({
    name: '', lat: null, lon: null, country_code: null, address: null,
  });
  let origin = $state<PickedPlace>(emptyPlace());
  /* A list, not a field — see AddTripPage. One empty row when the trip has
   * none, so the control is visible without a click. */
  let destinations = $state<PickedPlace[]>([emptyPlace()]);

  /* The span the trip's *contents* need. The dates on this form are the span
   * the traveller declares, and `_recompute_span` unions the two — so shortening
   * the trip past an existing leg is not an error, it simply has no effect on
   * that end, which from here looks like the save silently not working. Naming
   * what is holding the date is more use than refusing the edit: the trip may
   * legitimately be edited first and the leg fixed afterwards. */
  let contentStart = $state<string | null>(null);
  let contentEnd = $state<string | null>(null);

  const startTooLate = $derived(!!(startDate && contentStart && startDate > contentStart));
  const endTooEarly = $derived(!!(endDate && contentEnd && endDate < contentEnd));
  const spanWarning = $derived(
    (startTooLate || endTooEarly) && contentStart && contentEnd
      ? $t('edit_trip.span_held_by_legs', { values: { start: contentStart, end: contentEnd } })
      : '',
  );

  async function loadTrip() {
    try {
      const trip = await tripsApi.get(params.id);
      name = trip.name ?? '';
      startDate = trip.start_date ?? '';
      endDate = trip.end_date ?? '';
      origin = {
        name: trip.origin_place ?? '',
        lat: trip.origin_lat ?? null,
        lon: trip.origin_lon ?? null,
        country_code: trip.origin_country ?? null,
        address: null,
      };
      const listed = (trip.destinations ?? []).map((d) => ({
        name: d.name,
        lat: d.lat,
        lon: d.lon,
        country_code: d.country_code,
        address: null,
      }));
      destinations = listed.length ? listed : [emptyPlace()];
      seedPlacesFromFlights(trip);
      loadContentSpan(trip.flights ?? []);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  loadTrip();

  /* A trip built from email has airports but no typed cities, so this form
   * opened blank on exactly the trips that already knew where they went.
   *
   * The airport pair is derived and cannot hold a city, so the cities are
   * seeded into the *form* — offered as a filled-in default, saved only if the
   * traveller saves. Nothing is written behind their back, and anything they
   * already typed is left alone.
   *
   * The airport row carries coordinates and a country too, so the seed is a
   * complete place rather than a bare label: the country is the airport's,
   * which is a fact rather than a guess. */
  let seededFromFlights = $state(false);

  /** "Paris (Roissy-en-France)" → "Paris", "London, Essex" → "London". The same
   *  trimming the cover-photo lookup does on an airport's city name. */
  function cityOf(airport: { city_name?: string | null; iata_code: string }): string {
    const city = (airport.city_name ?? '').split('(')[0].split(',')[0].trim();
    return city || airport.iata_code;
  }

  async function placeFromAirport(iata: string): Promise<PickedPlace | null> {
    try {
      const airport = await airportsApi.get(iata);
      return {
        name: cityOf(airport),
        lat: airport.latitude ?? null,
        lon: airport.longitude ?? null,
        country_code: airport.country_code ?? null,
        address: null,
      };
    } catch {
      // No airport row, or the lookup failed: leave the field empty rather than
      // seeding an IATA code into a field that asks for a city.
      return null;
    }
  }

  async function seedPlacesFromFlights(trip: Trip) {
    const wantOrigin = !origin.name && !!trip.origin_airport;
    const wantDestination = !destinations.some((d) => d.name) && !!trip.destination_airport;
    if (!wantOrigin && !wantDestination) return;

    const [from, to] = await Promise.all([
      wantOrigin ? placeFromAirport(trip.origin_airport!) : null,
      wantDestination ? placeFromAirport(trip.destination_airport!) : null,
    ]);

    if (from) origin = from;
    if (to) destinations = [to];
    seededFromFlights = !!(from || to);
  }

  /** Earliest departure and latest arrival across everything on the trip, as
   *  local calendar dates. Best-effort: a failed lookup just means no warning,
   *  never a blocked edit. */
  async function loadContentSpan(flights: { departure_datetime: string | null; departure_timezone: string | null; arrival_datetime: string | null; arrival_timezone: string | null }[]) {
    const starts: string[] = [];
    const ends: string[] = [];

    for (const f of flights) {
      const from = localDateKey(f.departure_datetime, f.departure_timezone);
      const to = localDateKey(f.arrival_datetime, f.arrival_timezone);
      if (from) starts.push(from);
      if (to) ends.push(to);
    }

    const [segments, stays] = await Promise.all([
      segmentsApi.list(params.id).catch(() => []),
      staysApi.list(params.id).catch(() => []),
    ]);

    for (const seg of segments) {
      const from = localDateKey(seg.departure_datetime, seg.departure.timezone);
      const to = localDateKey(seg.arrival_datetime, seg.arrival.timezone);
      if (from) starts.push(from);
      if (to) ends.push(to);
    }
    // Stays already carry the local calendar dates at the property.
    for (const stay of stays) {
      if (stay.check_in_date) starts.push(stay.check_in_date);
      if (stay.check_out_date) ends.push(stay.check_out_date);
    }

    contentStart = starts.length ? starts.reduce((a, b) => (a < b ? a : b)) : null;
    contentEnd = ends.length ? ends.reduce((a, b) => (a > b ? a : b)) : null;
  }

  function placePayload(place: PickedPlace) {
    return {
      name: place.name.trim(),
      lat: place.lat,
      lon: place.lon,
      country_code: place.country_code,
    };
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    submitting = true;
    try {
      await tripsApi.update(params.id, {
        name: name.trim(),
        start_date: startDate || null,
        end_date: endDate || null,
        origin: placePayload(origin),
        destinations: destinations.map(placePayload).filter((p) => p.name),
      });

      await push(`/trips/${params.id}`);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      submitting = false;
    }
  }
</script>

<TopNav title={$t('edit_trip.title')} backHref={backUrl} />

<div class="main-content">
  {#if loading}
    <div class="loading-placeholder">{$t('trip.loading')}</div>
  {:else if loadError}
    <p class="form-error">{loadError}</p>
  {:else}
    <form class="page-form" onsubmit={submit}>

      <FormSection title={$t('add_trip.section_info')}>
        <label class="form-field">
          <span class="form-label">{$t('add_trip.name')} *</span>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            type="text"
            bind:value={name}
            placeholder={$t('add_trip.name_placeholder')}
            required
            class="form-input"
            autofocus
          />
        </label>

      </FormSection>

      <FormSection title={$t('add_trip.section_dates')}>
        <div class="form-row">
          <label class="form-field">
            <span class="form-label">{$t('add_trip.start_date')}</span>
            <input type="date" bind:value={startDate} class="form-input" />
          </label>
          <label class="form-field">
            <span class="form-label">{$t('add_trip.end_date')}</span>
            <input type="date" bind:value={endDate} class="form-input" />
          </label>
        </div>
      </FormSection>

      <!-- Cities, not airport codes: `origin_airport`/`destination_airport` are
           derived (`_recompute_span` rewrites both from the flights and nulls
           them when there are none), so nothing typed could ever survive there,
           and a trip that is driven has no airport to name. These are their own
           user-owned columns, and the destination also picks the cover photo. -->
      <FormSection title={$t('add_trip.section_route')}>
        <div class="form-row">
          <div class="form-field">
            <span class="form-label">{$t('trips.origin')}</span>
            <PlaceInput
              kind="city"
              value={origin.name}
              lat={origin.lat}
              lon={origin.lon}
              placeholder={$t('trips.origin_placeholder')}
              onchange={(p) => (origin = p)}
            />
          </div>
        </div>

        <div class="form-field">
          <span class="form-label">{$t('trips.destinations')}</span>
          {#each destinations as dest, i (i)}
            <div class="destination-row">
              <PlaceInput
                kind="city"
                value={dest.name}
                lat={dest.lat}
                lon={dest.lon}
                placeholder={$t('trips.destination_placeholder')}
                onchange={(p) => (destinations[i] = p)}
              />
              {#if destinations.length > 1}
                <button
                  type="button"
                  class="btn btn-secondary btn-sm destination-remove"
                  aria-label={$t('trips.destination_remove')}
                  onclick={() => (destinations = destinations.filter((_, n) => n !== i))}
                >✕</button>
              {/if}
            </div>
          {/each}
          <button
            type="button"
            class="btn btn-secondary btn-sm destination-add"
            onclick={() => (destinations = [...destinations, emptyPlace()])}
          >+ {$t('trips.destination_add')}</button>
        </div>
        <p class="form-hint">{$t('trips.route_hint')}</p>
        {#if seededFromFlights}
          <!-- Say where they came from: a field that fills itself is otherwise
               indistinguishable from one the traveller filled and forgot. -->
          <p class="form-hint">{$t('trips.route_seeded')}</p>
        {/if}
      </FormSection>

      {#if spanWarning}
        <!-- Advisory, never a block: the trip's span is its declared dates
             unioned with its contents, so this end simply will not move until
             the leg does. Saying which leg holds it beats a save that appears
             to do nothing. -->
        <p class="form-warning">{spanWarning}</p>
      {/if}

      {#if error}
        <p class="form-error">{error}</p>
      {/if}

      <div class="form-actions">
        <a href={backUrl} class="btn btn-secondary">{$t('add_trip.cancel')}</a>
        <button type="submit" class="btn btn-primary" disabled={submitting}>
          {submitting ? $t('edit_trip.saving') : $t('edit_trip.save')}
        </button>
      </div>

    </form>
  {/if}
</div>

<style>
  .loading-placeholder {
    text-align: center;
    padding: var(--space-xl);
    color: var(--text-muted);
  }
</style>
