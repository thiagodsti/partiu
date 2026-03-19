<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { tripsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import FormSection from '../components/FormSection.svelte';
  import AirportCombobox from '../components/AirportCombobox.svelte';
  import { t } from '../lib/i18n';

  let name = $state('');
  let startDate = $state('');
  let endDate = $state('');
  let originAirport = $state('');
  let destinationAirport = $state('');
  let bookingRefs = $state('');

  let submitting = $state(false);
  let error = $state<string | null>(null);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    submitting = true;
    try {
      const refs = bookingRefs
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);

      const result = await tripsApi.create({
        name:                name.trim(),
        start_date:          startDate || undefined,
        end_date:            endDate || undefined,
        origin_airport:      originAirport.trim().toUpperCase() || undefined,
        destination_airport: destinationAirport.trim().toUpperCase() || undefined,
        booking_refs:        refs.length ? refs : undefined,
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
