<script lang="ts">
  import { carRentalsApi } from '../api/client';
  import type { CarRentalWriteData, RentalPlaceInput } from '../api/client';
  import type { Trip, TripCarRental } from '../api/types';
  import { toLocalInputValue } from '../lib/utils';
  import { t } from '../lib/i18n';
  import CarRentalRow from './CarRentalRow.svelte';
  import PlaceInput from './PlaceInput.svelte';

  interface Props {
    trip: Trip;
    /** Called after load and after every mutation, so the trip page can feed
     * the day planner without fetching the list a second time — the same
     * contract TripStays has. */
    onchange?: (rentals: TripCarRental[]) => void;
  }

  const { trip, onchange }: Props = $props();

  /* The vendors whose confirmation emails are parsed, offered as a datalist
   * rather than a select: the list is a convenience, not a constraint, and a
   * rental from anyone else is an ordinary booking that must still save. */
  const KNOWN_VENDORS = ['Hertz', 'Sixt', 'Europcar', 'Avis', 'Enterprise', 'Budget'];

  /* Counter hours, as a starting point rather than a claim — every branch sets
   * its own, and both stay editable. Morning collection and a same-hour return
   * is the shape of the measured bookings. */
  const DEFAULT_PICKUP = '09:00';
  const DEFAULT_DROPOFF = '09:00';

  let rentals = $state<TripCarRental[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);

  interface FormState {
    vendor: string;
    pickup: RentalPlaceInput;
    dropoff: RentalPlaceInput;
    pickup_datetime: string;
    dropoff_datetime: string;
    booking_reference: string;
    vehicle: string;
    driver_name: string;
    notes: string;
    /** Whether the car comes back where it was collected. Form-only: the
     * backend derives `is_one_way` from the two places. Defaulting to true
     * matches the common hire and halves the form for it. */
    sameReturn: boolean;
  }

  function emptyPlace(): RentalPlaceInput {
    return { name: '', address: '', lat: null, lon: null, country_code: null };
  }

  function emptyForm(): FormState {
    return {
      vendor: '',
      pickup: emptyPlace(),
      dropoff: emptyPlace(),
      pickup_datetime: '',
      dropoff_datetime: '',
      booking_reference: '',
      vehicle: '',
      driver_name: '',
      notes: '',
      sameReturn: true,
    };
  }

  function formFromRental(r: TripCarRental): FormState {
    return {
      vendor: r.vendor,
      pickup: {
        name: r.pickup.name,
        address: r.pickup.address ?? '',
        lat: r.pickup.lat,
        lon: r.pickup.lon,
        country_code: r.pickup.country_code,
      },
      dropoff: {
        name: r.dropoff.name,
        address: r.dropoff.address ?? '',
        lat: r.dropoff.lat,
        lon: r.dropoff.lon,
        country_code: r.dropoff.country_code,
      },
      // Stored as UTC; the form edits wall-clock time at each counter.
      pickup_datetime: toLocalInputValue(r.pickup_datetime, r.pickup.timezone),
      dropoff_datetime: toLocalInputValue(r.dropoff_datetime, r.dropoff.timezone),
      booking_reference: r.booking_reference ?? '',
      vehicle: r.vehicle ?? '',
      driver_name: r.driver_name ?? '',
      notes: r.notes ?? '',
      sameReturn: !r.is_one_way,
    };
  }

  let showForm = $state(false);
  let editingId = $state<string | null>(null);
  let form = $state<FormState>(emptyForm());
  let saving = $state(false);
  let formError = $state<string | null>(null);

  /** A picked result fills the address and country in; typing clears them,
   * because the name no longer refers to that place. Same rule as the stay
   * picker. */
  function pickPlace(
    end: 'pickup' | 'dropoff',
    p: { name: string; lat: number | null; lon: number | null; country_code: string | null; address: string | null },
  ) {
    const current = form[end];
    form[end] = {
      name: p.name,
      address: p.address ?? (p.lat === null ? current.address : ''),
      lat: p.lat,
      lon: p.lon,
      country_code: p.country_code,
    };
  }

  /* Floor for the drop-off picker: midnight on the **pickup day**, not the
   * pickup instant. A min carrying the 09:30 collection time makes that day's
   * earlier hours invalid, and pickers express that by greying the whole day —
   * so the day you actually collect the car reads as disabled. Date-granular
   * greys out only the days before; the same-day-but-earlier case is caught by
   * `dropBeforePick` below, which can say what is wrong. Same rule, and the
   * same trap, as TripStays' checkOutMin and AddTransportPage's bounds. */
  const dropoffMin = $derived(
    form.pickup_datetime ? `${form.pickup_datetime.slice(0, 10)}T00:00` : undefined,
  );

  /** Set when the drop-off is at or before the pickup. Its own flag rather than
   * a falsy `formValid`, so the form can say which field is wrong. */
  const dropBeforePick = $derived(
    form.pickup_datetime.length > 0 &&
      form.dropoff_datetime.length > 0 &&
      form.dropoff_datetime <= form.pickup_datetime,
  );

  const formValid = $derived(
    form.vendor.trim().length > 0 &&
      form.pickup.name.trim().length > 0 &&
      (form.sameReturn || form.dropoff.name.trim().length > 0) &&
      form.pickup_datetime.length > 0 &&
      form.dropoff_datetime.length > 0 &&
      form.dropoff_datetime > form.pickup_datetime,
  );

  async function load() {
    try {
      rentals = await carRentalsApi.list(trip.id);
      loadError = null;
      onchange?.(rentals);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  function openAdd() {
    form = emptyForm();
    // Seed both ends from the trip, which is right far more often than an empty
    // field: a car is hired for the trip it is on.
    if (trip.start_date) form.pickup_datetime = `${trip.start_date}T${DEFAULT_PICKUP}`;
    if (trip.end_date) form.dropoff_datetime = `${trip.end_date}T${DEFAULT_DROPOFF}`;
    editingId = null;
    formError = null;
    showForm = true;
  }

  function openEdit(r: TripCarRental) {
    form = formFromRental(r);
    editingId = r.id;
    formError = null;
    showForm = true;
  }

  function closeForm() {
    showForm = false;
    editingId = null;
    formError = null;
  }

  function payload(): CarRentalWriteData {
    const pickup = {
      name: form.pickup.name.trim(),
      address: (form.pickup.address ?? '').trim() || null,
      lat: form.pickup.lat,
      lon: form.pickup.lon,
      country_code: form.pickup.country_code,
    };
    // A return hire sends the pickup counter as both ends, so the backend's
    // `is_one_way` comes out false without the form having to say so.
    const dropoff = form.sameReturn
      ? { ...pickup }
      : {
          name: form.dropoff.name.trim(),
          address: (form.dropoff.address ?? '').trim() || null,
          lat: form.dropoff.lat,
          lon: form.dropoff.lon,
          country_code: form.dropoff.country_code,
        };
    return {
      vendor: form.vendor.trim(),
      pickup,
      dropoff,
      pickup_datetime: form.pickup_datetime,
      dropoff_datetime: form.dropoff_datetime,
      booking_reference: form.booking_reference.trim() || null,
      vehicle: form.vehicle.trim() || null,
      driver_name: form.driver_name.trim() || null,
      notes: form.notes.trim() || null,
    };
  }

  async function save() {
    if (!formValid || saving) return;
    saving = true;
    formError = null;
    try {
      if (editingId) await carRentalsApi.update(trip.id, editingId, payload());
      else await carRentalsApi.create(trip.id, payload());
      closeForm();
      await load();
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      saving = false;
    }
  }

  async function removeEditing() {
    if (!editingId) return;
    const r = rentals.find((x) => x.id === editingId);
    if (!r) return;
    if (!confirm($t('car_rentals.delete_confirm', { values: { vendor: r.vendor } }))) return;
    try {
      await carRentalsApi.delete(trip.id, editingId);
      closeForm();
      await load();
    } catch (err) {
      formError = (err as Error).message;
    }
  }
</script>

{#if loadError}
  <p class="rentals-empty" style="color:var(--danger)">{loadError}</p>
{/if}

{#each rentals as rental (rental.id)}
  <CarRentalRow {rental} onedit={openEdit} />
{/each}

{#if rentals.length === 0 && !loading && !loadError}
  <p class="rentals-empty">{$t('car_rentals.empty')}</p>
{/if}

{#if showForm}
  <div class="rental-form">
    <div class="rental-form-row">
      <label class="rental-field">
        <span class="rental-label">{$t('car_rentals.vendor')}</span>
        <input class="form-input" type="text" list="car-rental-vendors"
               bind:value={form.vendor}
               placeholder={$t('car_rentals.vendor_placeholder')} />
        <datalist id="car-rental-vendors">
          {#each KNOWN_VENDORS as v}<option value={v}></option>{/each}
        </datalist>
      </label>
      <label class="rental-field">
        <span class="rental-label">{$t('car_rentals.vehicle')}</span>
        <input class="form-input" type="text" bind:value={form.vehicle}
               placeholder={$t('car_rentals.vehicle_placeholder')} />
      </label>
    </div>

    <div class="rental-form-row">
      <div class="rental-field rental-field-wide">
        <span class="rental-label">{$t('car_rentals.pickup_place')}</span>
        <PlaceInput
          value={form.pickup.name ?? ''}
          lat={form.pickup.lat ?? null}
          lon={form.pickup.lon ?? null}
          kind="stay"
          placeholder={$t('car_rentals.pickup_place_placeholder')}
          onchange={(p) => pickPlace('pickup', p)}
        />
      </div>
    </div>

    <label class="rental-check">
      <input type="checkbox" bind:checked={form.sameReturn} />
      <span>{$t('car_rentals.same_return')}</span>
    </label>

    {#if !form.sameReturn}
      <div class="rental-form-row">
        <div class="rental-field rental-field-wide">
          <span class="rental-label">{$t('car_rentals.dropoff_place')}</span>
          <PlaceInput
            value={form.dropoff.name ?? ''}
            lat={form.dropoff.lat ?? null}
            lon={form.dropoff.lon ?? null}
            kind="stay"
            placeholder={$t('car_rentals.dropoff_place_placeholder')}
            onchange={(p) => pickPlace('dropoff', p)}
          />
        </div>
      </div>
    {/if}

    <div class="rental-form-row">
      <label class="rental-field">
        <span class="rental-label">{$t('car_rentals.pickup_time')}</span>
        <input class="form-input" type="datetime-local" bind:value={form.pickup_datetime} />
      </label>
      <label class="rental-field">
        <span class="rental-label">{$t('car_rentals.dropoff_time')}</span>
        <input class="form-input" type="datetime-local"
               min={dropoffMin}
               bind:value={form.dropoff_datetime} />
      </label>
    </div>

    <div class="rental-form-row">
      <label class="rental-field">
        <span class="rental-label">{$t('car_rentals.booking_ref')}</span>
        <input class="form-input" type="text" bind:value={form.booking_reference} />
      </label>
      <label class="rental-field">
        <span class="rental-label">{$t('car_rentals.driver')}</span>
        <input class="form-input" type="text" bind:value={form.driver_name} />
      </label>
    </div>

    <div class="rental-form-row">
      <label class="rental-field rental-field-wide">
        <span class="rental-label">{$t('car_rentals.notes')}</span>
        <input class="form-input" type="text" bind:value={form.notes} />
      </label>
    </div>

    {#if dropBeforePick}
      <p class="rental-error">{$t('car_rentals.error_dropoff_order')}</p>
    {/if}

    {#if formError}
      <p class="rental-error">{formError}</p>
    {/if}

    <div class="rental-form-actions">
      <button class="btn btn-primary btn-sm" disabled={!formValid || saving} onclick={save}>
        {saving ? $t('car_rentals.saving') : $t('car_rentals.save')}
      </button>
      <button class="btn btn-secondary btn-sm" onclick={closeForm}>{$t('car_rentals.cancel')}</button>
      {#if editingId}
        <button class="btn btn-secondary btn-sm rental-delete" onclick={removeEditing}>
          {$t('car_rentals.delete')}
        </button>
      {/if}
    </div>
  </div>
{:else}
  <button class="btn btn-secondary btn-sm rentals-add" onclick={openAdd}>
    + {$t('car_rentals.add')}
  </button>
{/if}

<style>
  .rentals-empty {
    font-size: 0.85rem;
    color: var(--text-muted, #64748b);
    margin: 0 0 var(--space-sm, 8px);
  }

  .rental-form {
    display: flex;
    flex-direction: column;
    gap: 9px;
    margin-top: var(--space-sm, 8px);
    padding: 11px;
    border: 1px solid var(--border, #e2e8f0);
    border-radius: var(--radius-md, 8px);
    background: var(--surface-alt, var(--surface, #fff));
  }

  .rental-form-row {
    display: flex;
    flex-wrap: wrap;
    gap: 9px;
  }

  .rental-field {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    min-width: 160px;
  }

  .rental-field-wide {
    flex-basis: 100%;
  }

  .rental-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted, #64748b);
  }

  .rental-check {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.82rem;
  }

  .rental-error {
    margin: 0;
    font-size: 0.8rem;
    color: var(--danger, #dc2626);
  }

  .rental-form-actions {
    display: flex;
    gap: 6px;
  }

  .rental-delete {
    margin-left: auto;
    color: var(--danger, #dc2626);
  }

  .rentals-add {
    align-self: flex-start;
    margin-top: var(--space-sm, 8px);
  }
</style>
