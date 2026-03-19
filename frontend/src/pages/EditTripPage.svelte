<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { tripsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import FormSection from '../components/FormSection.svelte';
  import AirportCombobox from '../components/AirportCombobox.svelte';
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
  let originAirport = $state('');
  let destinationAirport = $state('');
  let bookingRefs = $state('');

  async function loadTrip() {
    try {
      const trip = await tripsApi.get(params.id);
      name = trip.name ?? '';
      startDate = trip.start_date ?? '';
      endDate = trip.end_date ?? '';
      originAirport = trip.origin_airport ?? '';
      destinationAirport = trip.destination_airport ?? '';
      bookingRefs = (trip.booking_refs ?? []).join(', ');
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  loadTrip();

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    submitting = true;
    try {
      const refs = bookingRefs
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);

      await tripsApi.update(params.id, {
        name: name.trim(),
        start_date: startDate || null,
        end_date: endDate || null,
        origin_airport: originAirport.trim().toUpperCase() || null,
        destination_airport: destinationAirport.trim().toUpperCase() || null,
        booking_refs: refs,
      });

      // Refresh the trip image after saving since destination may have changed
      await tripsApi.refreshImage(params.id).catch(() => {});

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

        <label class="form-field">
          <span class="form-label">{$t('add_trip.booking_refs')}</span>
          <input
            type="text"
            bind:value={bookingRefs}
            placeholder="ABC123, XYZ789"
            autocomplete="off"
            class="form-input mono"
            style="text-transform:uppercase"
          />
          <span class="form-hint">{$t('add_trip.booking_refs_hint')}</span>
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

      <FormSection title={$t('add_trip.section_route')}>
        <div class="form-row">
          <label class="form-field">
            <span class="form-label">{$t('add_trip.origin')}</span>
            <AirportCombobox bind:value={originAirport} placeholder={$t('add_trip.origin')} />
          </label>
          <label class="form-field">
            <span class="form-label">{$t('add_trip.destination')}</span>
            <AirportCombobox bind:value={destinationAirport} placeholder={$t('add_trip.destination')} />
          </label>
        </div>
        <p class="form-hint">{$t('edit_trip.image_hint')}</p>
      </FormSection>

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
