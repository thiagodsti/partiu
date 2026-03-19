<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { flightsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import AirportCombobox from '../components/AirportCombobox.svelte';
  import { t } from '../lib/i18n';

  interface Props {
    params: { tripId: string };
  }
  const { params }: Props = $props();

  const backUrl = $derived(`#/trips/${params.tripId}`);

  // ---- Form state ----
  let flightNumber = $state('');
  let airlineName = $state('');
  let airlineCode = $state('');
  let departureAirport = $state('');
  let departureDatetime = $state('');
  let arrivalAirport = $state('');
  let arrivalDatetime = $state('');
  let bookingReference = $state('');
  let passengerName = $state('');
  let seat = $state('');
  let cabinClass = $state('');
  let departureTerminal = $state('');
  let departureGate = $state('');
  let arrivalTerminal = $state('');
  let arrivalGate = $state('');
  let notes = $state('');

  let submitting = $state(false);
  let error = $state<string | null>(null);

  // Auto-derive airline code from flight number (first 2 letters)
  $effect(() => {
    const match = flightNumber.trim().match(/^([A-Za-z]{2})\d/);
    if (match && !airlineCode) {
      airlineCode = match[1].toUpperCase();
    }
  });

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    submitting = true;
    try {
      await flightsApi.create({
        flight_number:      flightNumber.trim().toUpperCase(),
        airline_name:       airlineName.trim(),
        airline_code:       airlineCode.trim().toUpperCase(),
        departure_airport:  departureAirport.trim().toUpperCase(),
        departure_datetime: departureDatetime,
        arrival_airport:    arrivalAirport.trim().toUpperCase(),
        arrival_datetime:   arrivalDatetime,
        booking_reference:  bookingReference.trim().toUpperCase(),
        passenger_name:     passengerName.trim(),
        seat:               seat.trim(),
        cabin_class:        cabinClass,
        departure_terminal: departureTerminal.trim(),
        departure_gate:     departureGate.trim(),
        arrival_terminal:   arrivalTerminal.trim(),
        arrival_gate:       arrivalGate.trim(),
        notes:              notes.trim(),
        trip_id:            params.tripId,
      });
      await push(`/trips/${params.tripId}`);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      submitting = false;
    }
  }
</script>

<TopNav title={$t('add_flight.title')} backHref={backUrl} />

<div class="main-content">
  <form class="add-flight-form" onsubmit={submit}>

    <!-- Route (required) -->
    <section class="form-section">
      <div class="form-section-title">{$t('add_flight.section_route')}</div>

      <div class="form-row">
        <label class="form-field">
          <span class="form-label">{$t('add_flight.flight_number')} *</span>
          <input
            type="text"
            bind:value={flightNumber}
            placeholder="LA800"
            required
            autocomplete="off"
            class="form-input mono"
            style="text-transform:uppercase"
          />
        </label>
        <label class="form-field">
          <span class="form-label">{$t('add_flight.airline_code')}</span>
          <input
            type="text"
            bind:value={airlineCode}
            placeholder="LA"
            maxlength="3"
            autocomplete="off"
            class="form-input mono"
            style="text-transform:uppercase"
          />
        </label>
      </div>

      <label class="form-field">
        <span class="form-label">{$t('add_flight.airline_name')}</span>
        <input
          type="text"
          bind:value={airlineName}
          placeholder="LATAM Airlines"
          autocomplete="off"
          class="form-input"
        />
      </label>
    </section>

    <!-- Departure (required) -->
    <section class="form-section">
      <div class="form-section-title">{$t('add_flight.section_departure')}</div>

      <div class="form-row">
        <div class="form-field" style="flex:0 0 180px">
          <span class="form-label">{$t('add_flight.airport')} *</span>
          <AirportCombobox bind:value={departureAirport} placeholder="GRU" required />
        </div>
        <label class="form-field" style="flex:1">
          <span class="form-label">{$t('add_flight.datetime')} *</span>
          <input
            type="datetime-local"
            bind:value={departureDatetime}
            required
            class="form-input"
          />
        </label>
      </div>

      <div class="form-row">
        <label class="form-field">
          <span class="form-label">{$t('add_flight.terminal')}</span>
          <input type="text" bind:value={departureTerminal} placeholder="A" class="form-input mono" />
        </label>
        <label class="form-field">
          <span class="form-label">{$t('add_flight.gate')}</span>
          <input type="text" bind:value={departureGate} placeholder="A12" class="form-input mono" />
        </label>
      </div>
    </section>

    <!-- Arrival (required) -->
    <section class="form-section">
      <div class="form-section-title">{$t('add_flight.section_arrival')}</div>

      <div class="form-row">
        <div class="form-field" style="flex:0 0 180px">
          <span class="form-label">{$t('add_flight.airport')} *</span>
          <AirportCombobox bind:value={arrivalAirport} placeholder="SCL" required />
        </div>
        <label class="form-field" style="flex:1">
          <span class="form-label">{$t('add_flight.datetime')} *</span>
          <input
            type="datetime-local"
            bind:value={arrivalDatetime}
            required
            class="form-input"
          />
        </label>
      </div>

      <div class="form-row">
        <label class="form-field">
          <span class="form-label">{$t('add_flight.terminal')}</span>
          <input type="text" bind:value={arrivalTerminal} placeholder="2" class="form-input mono" />
        </label>
        <label class="form-field">
          <span class="form-label">{$t('add_flight.gate')}</span>
          <input type="text" bind:value={arrivalGate} placeholder="B4" class="form-input mono" />
        </label>
      </div>
    </section>

    <!-- Booking details (optional) -->
    <section class="form-section">
      <div class="form-section-title">{$t('add_flight.section_booking')}</div>

      <div class="form-row">
        <label class="form-field">
          <span class="form-label">{$t('add_flight.booking_ref')}</span>
          <input
            type="text"
            bind:value={bookingReference}
            placeholder="ABC123"
            autocomplete="off"
            class="form-input mono"
            style="text-transform:uppercase"
          />
        </label>
        <label class="form-field">
          <span class="form-label">{$t('add_flight.passenger')}</span>
          <input
            type="text"
            bind:value={passengerName}
            placeholder="SILVA/JOAO"
            class="form-input"
          />
        </label>
      </div>

      <div class="form-row">
        <label class="form-field">
          <span class="form-label">{$t('add_flight.seat')}</span>
          <input type="text" bind:value={seat} placeholder="12A" class="form-input mono" />
        </label>
        <label class="form-field">
          <span class="form-label">{$t('add_flight.cabin_class')}</span>
          <select bind:value={cabinClass} class="form-input">
            <option value="">—</option>
            <option value="economy">{$t('add_flight.cabin_economy')}</option>
            <option value="premium economy">{$t('add_flight.cabin_premium')}</option>
            <option value="business">{$t('add_flight.cabin_business')}</option>
            <option value="first">{$t('add_flight.cabin_first')}</option>
          </select>
        </label>
      </div>
    </section>

    <!-- Notes (optional) -->
    <section class="form-section">
      <label class="form-field">
        <span class="form-label">{$t('add_flight.notes')}</span>
        <textarea
          bind:value={notes}
          rows="3"
          placeholder={$t('add_flight.notes_placeholder')}
          class="form-input"
          style="resize:vertical"
        ></textarea>
      </label>
    </section>

    {#if error}
      <p class="form-error">{error}</p>
    {/if}

    <div class="form-actions">
      <a href={backUrl} class="btn btn-secondary">{$t('add_flight.cancel')}</a>
      <button type="submit" class="btn btn-primary" disabled={submitting}>
        {submitting ? $t('add_flight.saving') : $t('add_flight.save')}
      </button>
    </div>

  </form>
</div>

<style>
  .add-flight-form {
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
