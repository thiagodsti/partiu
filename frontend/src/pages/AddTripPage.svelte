<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { tripsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import FormSection from '../components/FormSection.svelte';
  import PlaceInput from '../components/PlaceInput.svelte';
  import type { PickedPlace } from '../api/types';
  import { t } from '../lib/i18n';

  let name = $state('');
  let startDate = $state('');
  let endDate = $state('');

  /** The trip's own ends, as cities rather than airport codes — a drive from
   *  Florianópolis to São Paulo has both, and neither is an airport. Stored in
   *  their own columns: the `*_airport` pair is derived from the flights and
   *  rewritten on every change, so nothing typed could ever survive there. */
  const emptyPlace = (): PickedPlace => ({
    name: '', lat: null, lon: null, country_code: null, address: null,
  });
  let origin = $state<PickedPlace>(emptyPlace());
  /* A trip goes to more than one place — a fortnight in Brazil is São Paulo
   * *and* Rio. The list starts with one empty row so the field is visible
   * without a click; blank rows are dropped on save. */
  let destinations = $state<PickedPlace[]>([emptyPlace()]);

  let submitting = $state(false);
  let error = $state<string | null>(null);

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
      const result = await tripsApi.create({
        name:                name.trim(),
        start_date:          startDate || undefined,
        end_date:            endDate || undefined,
        origin:              placePayload(origin),
        destinations:        destinations.map(placePayload).filter((p) => p.name),
      });
      await push(`/trips/${result.id}`);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      submitting = false;
    }
  }
</script>

<TopNav title={$t('add_trip.title')} backHref="#/trips" />

<div class="main-content">
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
      <span class="form-hint">{$t('trips.route_hint')}</span>
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

    {#if error}<p class="form-error">{error}</p>{/if}

    <div class="form-actions">
      <a href="#/trips" class="btn btn-secondary">{$t('add_trip.cancel')}</a>
      <button type="submit" class="btn btn-primary" disabled={submitting}>
        {submitting ? $t('add_trip.saving') : $t('add_trip.save')}
      </button>
    </div>

  </form>
</div>
