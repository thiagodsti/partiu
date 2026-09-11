<script lang="ts">
  import { location, push } from 'svelte-spa-router';
  import { flightsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import FormSection from '../components/FormSection.svelte';
  import AirportCombobox from '../components/AirportCombobox.svelte';
  import { toLocalInputValue } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    params: { tripId: string; flightId: string };
  }
  const { params }: Props = $props();

  // The flight detail page is reachable from both /trips and /history, and the
  // edit page inherits whichever one the user came through so Back/Cancel land
  // where they started.
  const basePath = $derived($location.startsWith('/history') ? 'history' : 'trips');
  const backUrl = $derived(`#/${basePath}/${params.tripId}/flights/${params.flightId}`);

  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let submitting = $state(false);
  let error = $state<string | null>(null);

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

  async function loadFlight() {
    try {
      const f = await flightsApi.get(params.flightId);
      flightNumber = f.flight_number ?? '';
      airlineName = f.airline_name ?? '';
      airlineCode = f.airline_code ?? '';
      departureAirport = f.departure_airport ?? '';
      arrivalAirport = f.arrival_airport ?? '';
      // Times are stored in UTC; the form edits wall-clock time at each airport,
      // which is also what the backend expects back (it re-localises on save).
      departureDatetime = toLocalInputValue(f.departure_datetime, f.departure_timezone);
      arrivalDatetime = toLocalInputValue(f.arrival_datetime, f.arrival_timezone);
      bookingReference = f.booking_reference ?? '';
      passengerName = f.passenger_name ?? '';
      seat = f.seat ?? '';
      cabinClass = f.cabin_class ?? '';
      departureTerminal = f.departure_terminal ?? '';
      departureGate = f.departure_gate ?? '';
      arrivalTerminal = f.arrival_terminal ?? '';
      arrivalGate = f.arrival_gate ?? '';
      notes = f.notes ?? '';
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  loadFlight();

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    submitting = true;
    try {
      await flightsApi.update(params.flightId, {
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
      });
      await push(`/${basePath}/${params.tripId}/flights/${params.flightId}`);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      submitting = false;
    }
  }
</script>

<TopNav title={$t('edit_flight.title')} backHref={backUrl} />

<div class="main-content">
  {#if loading}
    <div class="loading-placeholder">{$t('flight.loading')}</div>
  {:else if loadError}
    <p class="form-error">{loadError}</p>
  {:else}
    <form class="page-form" onsubmit={submit}>

      <!-- Route (required) -->
      <FormSection title={$t('add_flight.section_route')}>
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
      </FormSection>

      <!-- Departure (required) -->
      <FormSection title={$t('add_flight.section_departure')}>
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
      </FormSection>

      <!-- Arrival (required) -->
      <FormSection title={$t('add_flight.section_arrival')}>
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
      </FormSection>

      <!-- Booking details (optional) -->
      <FormSection title={$t('add_flight.section_booking')}>
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
      </FormSection>

      <!-- Notes (optional) -->
      <FormSection>
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
      </FormSection>

      {#if error}
        <p class="form-error">{error}</p>
      {/if}

      <div class="form-actions">
        <a href={backUrl} class="btn btn-secondary">{$t('add_flight.cancel')}</a>
        <button type="submit" class="btn btn-primary" disabled={submitting}>
          {submitting ? $t('edit_flight.saving') : $t('edit_flight.save')}
        </button>
      </div>

    </form>
  {/if}
</div>
