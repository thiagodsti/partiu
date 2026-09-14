<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { flightsApi, segmentsApi, tripsApi } from '../api/client';
  import type { SegmentWriteData, SegmentPlaceInput } from '../api/client';
  import type { SegmentType } from '../api/types';
  import TopNav from '../components/TopNav.svelte';
  import FormSection from '../components/FormSection.svelte';
  import AirportCombobox from '../components/AirportCombobox.svelte';
  import PlaceInput from '../components/PlaceInput.svelte';
  import { t } from '../lib/i18n';

  interface Props {
    params: { tripId: string };
  }
  const { params }: Props = $props();

  const backUrl = $derived(`#/trips/${params.tripId}`);

  /* The trip's own span bounds both pickers. It is safe to bound with because
   * `_recompute_span` unions the *declared* dates (`planned_start_date` /
   * `planned_end_date`, typed on the trip form) with the contents — without
   * that, adding the first leg collapses the span to that leg's day and the
   * return leg would already fall outside its own trip.
   *
   * Both bounds are **date-granular** (`T00:00` / `T23:59`), for the reason the
   * stays picker documents: a min carrying a time makes that day's earlier
   * hours invalid, and browsers express that by greying out the whole day, so
   * the boundary day reads as broken. */
  let tripStart = $state<string | null>(null);
  let tripEnd = $state<string | null>(null);

  async function loadTripSpan() {
    try {
      const trip = await tripsApi.get(params.tripId);
      tripStart = trip.start_date ?? null;
      tripEnd = trip.end_date ?? null;
    } catch {
      // A trip whose dates cannot be read simply gets an unbounded picker: a
      // failed lookup must not stop you adding a leg.
    }
  }

  loadTripSpan();

  const minDatetime = $derived(tripStart ? `${tripStart}T00:00` : undefined);
  // Suppressed when it would sit before the floor — min > max greys out the
  // entire calendar, which reads as a broken picker rather than a bound.
  const maxDatetime = $derived(
    tripEnd && (!tripStart || tripEnd >= tripStart) ? `${tripEnd}T23:59` : undefined,
  );
  const rangeHint = $derived(
    tripStart && tripEnd ? $t('add_transport.range_hint', { values: { start: tripStart, end: tripEnd } }) : '',
  );

  /** A flight and a ground leg are two tables and two endpoints behind this
   *  form — `flights` carries fifteen flight-only columns and ten backend
   *  modules query it directly, so they are deliberately not one table with a
   *  discriminator (see migration 0023). Only the *entry point* is shared:
   *  nobody thinks "I will add a ground segment", they think "I need the
   *  Stockholm → Oslo leg", and the mode is a property of that leg. */
  type TransportType = 'flight' | SegmentType;

  const TYPES: TransportType[] = ['flight', 'train', 'bus', 'ferry', 'car'];

  const TYPE_ICONS: Record<TransportType, string> = {
    flight: '✈️',
    train: '🚆',
    bus: '🚌',
    ferry: '⛴️',
    car: '🚗',
  };

  let type = $state<TransportType>('flight');
  const isFlight = $derived(type === 'flight');
  /* A car has no seat to be assigned — you are the one driving. The field is
   * hidden rather than relabelled, and the payload drops whatever was typed
   * before the switch so a stale "Vagão 3" cannot ride along on a drive. */
  const hasSeat = $derived(type !== 'car');

  // ---- Shared across both modes ----
  // Times and booking details survive a change of type on purpose: realising a
  // leg is a train after typing its times should not cost you the times.
  let departureDatetime = $state('');
  let arrivalDatetime = $state('');
  let bookingReference = $state('');
  let seat = $state('');

  // ---- Flight only ----
  let flightNumber = $state('');
  let airlineName = $state('');
  let airlineCode = $state('');
  let departureAirport = $state('');
  let arrivalAirport = $state('');
  let departureTerminal = $state('');
  let departureGate = $state('');
  let arrivalTerminal = $state('');
  let arrivalGate = $state('');
  let cabinClass = $state('');
  let passengerName = $state('');
  let notes = $state('');

  // ---- Ground only ----
  const emptyPlace = (): SegmentPlaceInput => ({ name: '', lat: null, lon: null, country_code: null });
  let departurePlace = $state<SegmentPlaceInput>(emptyPlace());
  let arrivalPlace = $state<SegmentPlaceInput>(emptyPlace());
  let operator = $state('');
  let serviceNumber = $state('');

  let submitting = $state(false);
  let error = $state<string | null>(null);

  // Auto-derive airline code from flight number (first 2 letters)
  $effect(() => {
    const match = flightNumber.trim().match(/^([A-Za-z]{2})\d/);
    if (match && !airlineCode) {
      airlineCode = match[1].toUpperCase();
    }
  });

  const valid = $derived(
    departureDatetime.length > 0 &&
      arrivalDatetime.length > 0 &&
      (isFlight
        ? flightNumber.trim().length > 0 &&
          departureAirport.trim().length > 0 &&
          arrivalAirport.trim().length > 0
        : departurePlace.name.trim().length > 0 && arrivalPlace.name.trim().length > 0),
  );

  function segmentPayload(): SegmentWriteData {
    return {
      type: type as SegmentType,
      departure: departurePlace,
      arrival: arrivalPlace,
      departure_datetime: departureDatetime,
      arrival_datetime: arrivalDatetime,
      operator: operator.trim() || null,
      number: serviceNumber.trim() || null,
      booking_reference: bookingReference.trim() || null,
      seat: hasSeat ? seat.trim() || null : null,
    };
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!valid || submitting) return;
    error = null;
    submitting = true;
    try {
      if (isFlight) {
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
      } else {
        await segmentsApi.create(params.tripId, segmentPayload());
      }
      await push(`/trips/${params.tripId}`);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      submitting = false;
    }
  }
</script>

<TopNav title={$t('add_transport.title')} backHref={backUrl} />

{#snippet req()}<span class="req" aria-hidden="true">*</span>{/snippet}

<div class="main-content settings-page">
  <form class="page-form" onsubmit={submit}>

    <FormSection title={$t('segments.type')}>
      <div class="type-picker" role="radiogroup" aria-label={$t('segments.type')}>
        {#each TYPES as ty (ty)}
          <button
            type="button"
            class="type-option"
            class:selected={type === ty}
            role="radio"
            aria-checked={type === ty}
            onclick={() => (type = ty)}
          >
            <span class="type-icon" aria-hidden="true">{TYPE_ICONS[ty]}</span>
            <span>{ty === 'flight' ? $t('add_transport.type_flight') : $t(`segments.type_${ty}`)}</span>
          </button>
        {/each}
      </div>
      {#if rangeHint}
        <!-- A greyed-out calendar reads as a broken picker unless something on
             the page says what the range is and how to change it. -->
        <span class="form-hint">{rangeHint}</span>
      {/if}
    </FormSection>

    {#if isFlight}
      <FormSection title={$t('add_flight.section_route')}>
        <div class="form-row">
          <label class="form-field">
            <span class="form-label">{$t('add_flight.flight_number')} {@render req()}</span>
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
            <span class="form-label">{$t('add_flight.airline_name')}</span>
            <input
              type="text"
              bind:value={airlineName}
              placeholder="LATAM Airlines"
              autocomplete="off"
              class="form-input"
            />
          </label>
        </div>

        <div class="form-row">
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

      <FormSection title={$t('add_flight.section_departure')}>
        <div class="form-row">
          <div class="form-field" style="flex:0 0 180px">
            <span class="form-label">{$t('add_flight.airport')} {@render req()}</span>
            <AirportCombobox bind:value={departureAirport} placeholder="GRU" required />
          </div>
          <label class="form-field" style="flex:1 1 200px">
            <span class="form-label">{$t('add_flight.datetime')} {@render req()}</span>
            <input
              type="datetime-local"
              bind:value={departureDatetime}
              required
              min={minDatetime}
              max={maxDatetime}
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

      <FormSection title={$t('add_flight.section_arrival')}>
        <div class="form-row">
          <div class="form-field" style="flex:0 0 180px">
            <span class="form-label">{$t('add_flight.airport')} {@render req()}</span>
            <AirportCombobox bind:value={arrivalAirport} placeholder="SCL" required />
          </div>
          <label class="form-field" style="flex:1 1 200px">
            <span class="form-label">{$t('add_flight.datetime')} {@render req()}</span>
            <input
              type="datetime-local"
              bind:value={arrivalDatetime}
              required
              min={minDatetime}
              max={maxDatetime}
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
    {:else}
      <!-- Titled with the chosen type, not "Flight": this section was reusing the
           flight heading, so adding a ferry announced itself as a voo. -->
      <FormSection title={$t(`segments.type_${type}`)}>
        <div class="form-row">
          <label class="form-field">
            <span class="form-label">{$t('segments.operator')}</span>
            <input
              class="form-input"
              type="text"
              bind:value={operator}
              placeholder={$t('segments.operator_placeholder')}
            />
          </label>
          <label class="form-field">
            <span class="form-label">{$t('segments.number')}</span>
            <input
              class="form-input"
              type="text"
              bind:value={serviceNumber}
              placeholder={$t('segments.number_placeholder')}
            />
          </label>
        </div>
      </FormSection>

      <FormSection title={$t('add_flight.section_departure')}>
        <div class="form-row">
          <div class="form-field" style="flex:1 1 200px">
            <span class="form-label">{$t('segments.from')} {@render req()}</span>
            <PlaceInput
              value={departurePlace.name}
              lat={departurePlace.lat ?? null}
              lon={departurePlace.lon ?? null}
              kind={type as SegmentType}
              placeholder={$t('segments.from_placeholder')}
              onchange={(p) =>
                (departurePlace = { name: p.name, lat: p.lat, lon: p.lon, country_code: p.country_code })}
            />
          </div>
          <label class="form-field" style="flex:1 1 200px">
            <span class="form-label">{$t('segments.departs')} {@render req()}</span>
            <input
              type="datetime-local"
              bind:value={departureDatetime}
              required
              min={minDatetime}
              max={maxDatetime}
              class="form-input"
            />
          </label>
        </div>
      </FormSection>

      <FormSection title={$t('add_flight.section_arrival')}>
        <div class="form-row">
          <div class="form-field" style="flex:1 1 200px">
            <span class="form-label">{$t('segments.to')} {@render req()}</span>
            <PlaceInput
              value={arrivalPlace.name}
              lat={arrivalPlace.lat ?? null}
              lon={arrivalPlace.lon ?? null}
              kind={type as SegmentType}
              placeholder={$t('segments.to_placeholder')}
              onchange={(p) =>
                (arrivalPlace = { name: p.name, lat: p.lat, lon: p.lon, country_code: p.country_code })}
            />
          </div>
          <label class="form-field" style="flex:1 1 200px">
            <span class="form-label">{$t('segments.arrives')} {@render req()}</span>
            <input
              type="datetime-local"
              bind:value={arrivalDatetime}
              required
              min={minDatetime}
              max={maxDatetime}
              class="form-input"
            />
          </label>
        </div>
      </FormSection>
    {/if}

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
        {#if hasSeat}
          <label class="form-field">
            <span class="form-label">{$t('add_flight.seat')}</span>
            <input
              type="text"
              bind:value={seat}
              placeholder={isFlight ? '12A' : $t('segments.seat_placeholder')}
              class="form-input mono"
            />
          </label>
        {/if}
      </div>

      {#if isFlight}
        <label class="form-field">
          <span class="form-label">{$t('add_flight.passenger')}</span>
          <input type="text" bind:value={passengerName} placeholder="SILVA/JOAO" class="form-input" />
        </label>
      {/if}
    </FormSection>

    {#if isFlight}
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
    {/if}

    {#if error}
      <p class="form-error">{error}</p>
    {/if}

    <div class="form-actions">
      <a href={backUrl} class="btn btn-secondary">{$t('add_flight.cancel')}</a>
      <button type="submit" class="btn btn-primary" disabled={!valid || submitting}>
        {submitting ? $t('add_flight.saving') : $t('add_transport.save')}
      </button>
    </div>

  </form>
</div>

<style>
  .type-picker {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-sm);
  }

  .type-option {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg-subtle);
    color: var(--text-primary);
    font: inherit;
    font-size: 0.9rem;
    cursor: pointer;
    /* Tap targets on a phone: the row wraps rather than shrinking the options. */
    min-height: 44px;
  }

  .type-option:hover {
    border-color: var(--border-strong);
  }

  /* The chosen type is the one filled control on the page, which is one of the
     four things allowed to wear the accent. `--accent-on` rather than white:
     the fill is near-white on the graphite preset, where white text vanishes. */
  .type-option.selected {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-on);
  }

  .type-icon {
    font-size: 1.05rem;
    line-height: 1;
  }

  /* Red is otherwise reserved for trouble in this design language. A required
     marker is the one long-standing exception readers already know, and the
     alternative — marking the optional majority instead — is more ink for less
     signal. `--danger-text` is the cut meant to be legible as text. */
  .req {
    color: var(--danger-text);
    font-weight: 700;
  }
</style>
