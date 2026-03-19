<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { tripsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import AirportCombobox from '../components/AirportCombobox.svelte';
  import { t } from '../lib/i18n';

  let name = $state('');
  let startDate = $state('');
  let endDate = $state('');
  let originAirport = $state('');
  let destinationAirport = $state('');
  let bookingRefs = $state('');   // comma-separated, split on submit

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
        name:                 name.trim(),
        start_date:           startDate || undefined,
        end_date:             endDate || undefined,
        origin_airport:       originAirport.trim().toUpperCase() || undefined,
        destination_airport:  destinationAirport.trim().toUpperCase() || undefined,
        booking_refs:         refs.length ? refs : undefined,
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
  <form class="add-trip-form" onsubmit={submit}>

    <section class="form-section">
      <div class="form-section-title">{$t('add_trip.section_info')}</div>

      <label class="form-field">
        <span class="form-label">{$t('add_trip.name')} *</span>
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
    </section>

    <section class="form-section">
      <div class="form-section-title">{$t('add_trip.section_dates')}</div>

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
    </section>

    <section class="form-section">
      <div class="form-section-title">{$t('add_trip.section_route')}</div>

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
    </section>

    {#if error}
      <p class="form-error">{error}</p>
    {/if}

    <div class="form-actions">
      <a href="#/trips" class="btn btn-secondary">{$t('add_trip.cancel')}</a>
      <button type="submit" class="btn btn-primary" disabled={submitting}>
        {submitting ? $t('add_trip.saving') : $t('add_trip.save')}
      </button>
    </div>

  </form>
</div>

<style>
  .add-trip-form {
    max-width: 540px;
    margin: 0 auto;
    padding: var(--space-md);
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
  }

  .form-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    padding: var(--space-md);
    background: var(--surface);
    border-radius: var(--radius);
    border: 1px solid var(--border);
  }

  .form-section-title {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: var(--space-xs);
  }

  .form-row {
    display: flex;
    gap: var(--space-sm);
  }

  .form-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
  }

  .form-label {
    font-size: 0.8rem;
    color: var(--text-muted);
    font-weight: 500;
  }

  .form-hint {
    font-size: 0.75rem;
    color: var(--text-muted);
    opacity: 0.8;
  }

  .form-input {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    background: var(--bg);
    color: var(--text);
    font-size: 0.9rem;
    box-sizing: border-box;
  }

  .form-input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent);
  }

  .mono {
    font-family: monospace;
  }

  .form-error {
    color: var(--error, #e53e3e);
    font-size: 0.875rem;
    padding: var(--space-sm);
    background: color-mix(in srgb, var(--error, #e53e3e) 10%, transparent);
    border-radius: var(--radius-sm, 6px);
    border: 1px solid color-mix(in srgb, var(--error, #e53e3e) 30%, transparent);
  }

  .form-actions {
    display: flex;
    gap: var(--space-sm);
    justify-content: flex-end;
    padding-bottom: var(--space-xl, 80px);
  }
</style>
