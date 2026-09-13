<script lang="ts">
  import { staysApi } from '../api/client';
  import type { StayWriteData, StayPlaceInput } from '../api/client';
  import type { Trip, Flight, TripSegment, TripStay, StayKind } from '../api/types';
  import { accommodationGaps, stayOutsideTravel, toLocalInputValue, formatDate } from '../lib/utils';
  import { t } from '../lib/i18n';
  import StayRow from './StayRow.svelte';
  import PlaceInput from './PlaceInput.svelte';

  interface Props {
    trip: Trip;
    flights: Flight[];
    segments: TripSegment[];
    /** Called after load and after every mutation, so the trip page can feed
     * the day planner without fetching the list a second time. */
    onchange?: (stays: TripStay[]) => void;
  }

  const { trip, flights, segments, onchange }: Props = $props();

  const KINDS: StayKind[] = ['hotel', 'airbnb', 'hostel', 'other'];

  const KIND_ICONS: Record<StayKind, string> = {
    hotel: '🏨',
    airbnb: '🏡',
    hostel: '🛏️',
    other: '📍',
  };

  let stays = $state<TripStay[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);

  // Uncovered nights are informational: they are the question "where am I
  // sleeping on the 14th?" answered before it is asked. Only shown once at
  // least one stay exists — listing every night of an unbooked trip is noise.
  const gaps = $derived(accommodationGaps(stays, trip.start_date, trip.end_date));

  function warningFor(stay: TripStay): string | null {
    const side = stayOutsideTravel(stay, flights, segments);
    if (!side) return null;
    if (side === 'before') return $t('stays.warn_before');
    if (side === 'after') return $t('stays.warn_after');
    return $t('stays.warn_overruns');
  }

  /* Hotel days, as a starting point rather than a claim: there is no single
   * standard — check-in is commonly 14:00–15:00 and check-out 10:00–12:00, and
   * every property sets its own. Both stay editable per stay. */
  const DEFAULT_CHECK_IN = '14:00';
  const DEFAULT_CHECK_OUT = '11:00';

  interface FormState {
    kind: StayKind;
    place: StayPlaceInput;
    check_in_datetime: string;
    check_out_datetime: string;
    booking_reference: string;
    confirmation: string;
    contact: string;
    room_type: string;
    guests: string;
    notes: string;
  }

  function emptyForm(): FormState {
    return {
      kind: 'hotel',
      place: { name: '', address: '', lat: null, lon: null, country_code: null },
      check_in_datetime: '',
      check_out_datetime: '',
      booking_reference: '',
      confirmation: '',
      contact: '',
      room_type: '',
      guests: '',
      notes: '',
    };
  }

  function formFromStay(s: TripStay): FormState {
    return {
      kind: s.kind,
      place: {
        name: s.place.name,
        address: s.place.address ?? '',
        lat: s.place.lat,
        lon: s.place.lon,
        country_code: s.place.country_code,
      },
      // Stored as UTC; the form edits wall-clock time at the property.
      check_in_datetime: toLocalInputValue(s.check_in_datetime, s.place.timezone),
      check_out_datetime: toLocalInputValue(s.check_out_datetime, s.place.timezone),
      booking_reference: s.booking_reference ?? '',
      confirmation: s.confirmation ?? '',
      contact: s.contact ?? '',
      room_type: s.room_type ?? '',
      guests: s.guests === null ? '' : String(s.guests),
      notes: s.notes ?? '',
    };
  }

  /** A picked result fills the address and country in; typing clears them,
   * because the name no longer refers to that place. The address stays
   * editable afterwards — what the geocoder knows and what the booking says
   * are not always the same, and the booking is what the guest turns up with. */
  function onPlacePicked(p: {
    name: string;
    lat: number | null;
    lon: number | null;
    country_code: string | null;
    address: string | null;
  }) {
    form.place = {
      name: p.name,
      address: p.address ?? (p.lat === null ? form.place.address : ''),
      lat: p.lat,
      lon: p.lon,
      country_code: p.country_code,
    };
  }

  let showForm = $state(false);
  let editingId = $state<string | null>(null);
  let form = $state<FormState>(emptyForm());
  let saving = $state(false);
  let formError = $state<string | null>(null);

  /* The last day the trip is travelling, from flights and ground legs only.
   *
   * Stays are excluded on purpose even though `trip.end_date` counts them: the
   * backend derives that date *from* the stays, so validating against it would
   * mean a stay could never be extended — the row being edited is itself what
   * sets the ceiling it would be measured against. Transport is the fixed
   * thing, and it is what "when the trip ends" means anyway. Null when the trip
   * has no transport at all, which bounds nothing. */
  const lastTravelDate = $derived.by(() => {
    const dates = [
      ...flights.map((f) => f.arrival_datetime),
      ...segments.map((sg) => sg.arrival_datetime),
    ]
      .filter((d): d is string => Boolean(d))
      .map((d) => d.slice(0, 10))
      .sort();
    return dates.length ? dates[dates.length - 1] : null;
  });

  /* Floor for the check-out picker: midnight on the **check-in day**, not the
   * check-in instant. Every earlier day greys out, which is the point, while
   * the check-in day itself stays fully selectable — a min carrying the 15:00
   * check-in time makes that day's earlier hours invalid, and pickers express
   * that by greying the whole day, so the boundary day reads as broken. The
   * same-day-but-earlier case is caught by `outBeforeIn` below, which can say
   * what is wrong instead of silently refusing a tap.
   *
   * Greyed-out days here have twice been reported as "the picker is broken";
   * both times the days really were out of range. Before removing this, check
   * that the dates being tried are not simply earlier than check-in. */
  const checkOutMin = $derived(
    form.check_in_datetime ? `${form.check_in_datetime.slice(0, 10)}T00:00` : undefined,
  );

  /* Ceiling for the check-out picker: the end of the last travel day, so that
   * whole day stays selectable (a check-out at 11:00 on the day you fly home is
   * the normal case), mirroring the date-granular floor above.
   *
   * Suppressed when it would sit before the floor. min > max greys out the
   * *entire* calendar, and an inverted range is reachable in ordinary use — a
   * one-way flight out with the return not added yet, then a check-in after it.
   * `afterTravel` still reports that case in words. */
  const checkOutMax = $derived.by(() => {
    if (!lastTravelDate) return undefined;
    if (form.check_in_datetime.slice(0, 10) > lastTravelDate) return undefined;
    return `${lastTravelDate}T23:59`;
  });

  /** Set when check-out is at or before check-in. Its own flag rather than
   * just a falsy `formValid`, so the form can say which field is wrong: a Save
   * button that is disabled for unstated reasons is a dead end. */
  const outBeforeIn = $derived(
    form.check_in_datetime.length > 0 &&
      form.check_out_datetime.length > 0 &&
      form.check_out_datetime <= form.check_in_datetime,
  );

  /** Set when the form's check-out would land after the trip's last transport. */
  const afterTravel = $derived(
    lastTravelDate !== null &&
      form.check_out_datetime.length > 0 &&
      form.check_out_datetime.slice(0, 10) > lastTravelDate,
  );

  const formValid = $derived(
    form.place.name.trim().length > 0 &&
      form.check_in_datetime.length > 0 &&
      form.check_out_datetime.length > 0 &&
      form.check_out_datetime > form.check_in_datetime &&
      !afterTravel,
  );

  async function load() {
    try {
      stays = await staysApi.list(trip.id);
      loadError = null;
      onchange?.(stays);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  function openAdd() {
    form = emptyForm();
    // Seed both ends, which is right far more often than an empty field is — a
    // stay is usually booked for the trip it is on, and runs from arrival to
    // departure. Check-out comes off the last transport rather than
    // `trip.end_date` for the same reason `afterTravel` does: end_date counts
    // other stays, so seeding from it could open the form already in error.
    if (trip.start_date) form.check_in_datetime = `${trip.start_date}T${DEFAULT_CHECK_IN}`;
    const out = lastTravelDate ?? trip.end_date;
    if (out) form.check_out_datetime = `${out}T${DEFAULT_CHECK_OUT}`;
    editingId = null;
    formError = null;
    showForm = true;
  }

  function openEdit(s: TripStay) {
    form = formFromStay(s);
    editingId = s.id;
    formError = null;
    showForm = true;
  }

  function closeForm() {
    showForm = false;
    editingId = null;
    formError = null;
  }

  function payload(): StayWriteData {
    const guests = parseInt(form.guests, 10);
    return {
      kind: form.kind,
      place: {
        name: form.place.name.trim(),
        address: (form.place.address ?? '').trim() || null,
        lat: form.place.lat,
        lon: form.place.lon,
        country_code: form.place.country_code,
      },
      check_in_datetime: form.check_in_datetime,
      check_out_datetime: form.check_out_datetime,
      booking_reference: form.booking_reference.trim() || null,
      confirmation: form.confirmation.trim() || null,
      contact: form.contact.trim() || null,
      room_type: form.room_type.trim() || null,
      guests: Number.isFinite(guests) && guests > 0 ? guests : null,
      notes: form.notes.trim() || null,
    };
  }

  async function save() {
    if (!formValid || saving) return;
    saving = true;
    formError = null;
    try {
      if (editingId) await staysApi.update(trip.id, editingId, payload());
      else await staysApi.create(trip.id, payload());
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
    const s = stays.find((x) => x.id === editingId);
    if (!s) return;
    if (!confirm($t('stays.delete_confirm', { values: { name: s.place.name } }))) return;
    try {
      await staysApi.delete(trip.id, editingId);
      closeForm();
      await load();
    } catch (err) {
      formError = (err as Error).message;
    }
  }
</script>

{#if loadError}
  <p class="stays-empty" style="color:var(--danger)">{loadError}</p>
{/if}

{#each stays as stay (stay.id)}
  <StayRow {stay} onedit={openEdit} warning={warningFor(stay)} />
{/each}

{#if stays.length === 0 && !loading && !loadError}
  <p class="stays-empty">{$t('stays.empty')}</p>
{/if}

{#if gaps.length > 0}
  <p class="stays-gaps">
    {$t(gaps.length === 1 ? 'stays.gaps' : 'stays.gaps_plural', { values: { count: gaps.length } })}
    <span class="stays-gap-dates">{gaps.map((d) => formatDate(d)).join(', ')}</span>
  </p>
{/if}

{#if showForm}
  <div class="stay-form">
    <div class="stay-form-row">
      <label class="stay-field">
        <span class="stay-label">{$t('stays.kind')}</span>
        <select class="form-input" bind:value={form.kind}>
          {#each KINDS as k}
            <option value={k}>{KIND_ICONS[k]} {$t(`stays.kind_${k}`)}</option>
          {/each}
        </select>
      </label>
      <div class="stay-field stay-field-wide">
        <span class="stay-label">{$t('stays.name')}</span>
        <PlaceInput
          value={form.place.name ?? ''}
          lat={form.place.lat ?? null}
          lon={form.place.lon ?? null}
          kind="stay"
          placeholder={$t('stays.name_placeholder')}
          onchange={onPlacePicked}
        />
      </div>
    </div>

    <div class="stay-form-row">
      <label class="stay-field stay-field-wide">
        <span class="stay-label">{$t('stays.address')}</span>
        <input class="form-input" type="text" bind:value={form.place.address}
               placeholder={$t('stays.address_placeholder')} />
        <span class="stay-hint">{$t('stays.address_hint')}</span>
      </label>
    </div>

    <div class="stay-form-row">
      <label class="stay-field">
        <span class="stay-label">{$t('stays.check_in')}</span>
        <input class="form-input" type="datetime-local" bind:value={form.check_in_datetime} />
      </label>
      <label class="stay-field">
        <span class="stay-label">{$t('stays.check_out')}</span>
        <input class="form-input" type="datetime-local"
               min={checkOutMin}
               max={checkOutMax}
               bind:value={form.check_out_datetime} />
      </label>
    </div>

    <div class="stay-form-row">
      <label class="stay-field">
        <span class="stay-label">{$t('stays.room_type')}</span>
        <input class="form-input" type="text" bind:value={form.room_type}
               placeholder={$t('stays.room_type_placeholder')} />
      </label>
      <label class="stay-field">
        <span class="stay-label">{$t('stays.guests')}</span>
        <input class="form-input" type="number" min="1" max="100" bind:value={form.guests} />
      </label>
      <label class="stay-field">
        <span class="stay-label">{$t('stays.booking_ref')}</span>
        <input class="form-input" type="text" bind:value={form.booking_reference} />
      </label>
    </div>

    <div class="stay-form-row">
      <label class="stay-field">
        <span class="stay-label">{$t('stays.confirmation')}</span>
        <input class="form-input" type="text" bind:value={form.confirmation} />
      </label>
      <label class="stay-field">
        <span class="stay-label">{$t('stays.contact')}</span>
        <input class="form-input" type="text" bind:value={form.contact}
               placeholder={$t('stays.contact_placeholder')} />
      </label>
    </div>

    <div class="stay-form-row">
      <label class="stay-field stay-field-wide">
        <span class="stay-label">{$t('stays.notes')}</span>
        <input class="form-input" type="text" bind:value={form.notes} />
      </label>
    </div>

    {#if outBeforeIn}
      <p class="stay-error">{$t('stays.error_check_out_order')}</p>
    {/if}

    {#if afterTravel}
      <p class="stay-error">
        {$t('stays.error_after_travel', { values: { date: formatDate(lastTravelDate) } })}
      </p>
    {/if}

    {#if formError}
      <p class="stay-error">{formError}</p>
    {/if}

    <div class="stay-form-actions">
      <button class="btn btn-primary btn-sm" disabled={!formValid || saving} onclick={save}>
        {saving ? $t('stays.saving') : $t('stays.save')}
      </button>
      <button class="btn btn-secondary btn-sm" onclick={closeForm}>{$t('stays.cancel')}</button>
      {#if editingId}
        <button class="btn btn-secondary btn-sm stay-delete" onclick={removeEditing}>
          {$t('stays.delete')}
        </button>
      {/if}
    </div>
  </div>
{:else}
  <button class="btn btn-secondary btn-sm stays-add" onclick={openAdd}>
    + {$t('stays.add')}
  </button>
{/if}

<style>
  .stays-empty {
    font-size: 0.85rem;
    color: var(--text-muted, #64748b);
    margin: 0 0 var(--space-sm, 8px);
  }

  .stays-gaps {
    margin: 0 0 var(--space-sm, 8px);
    font-size: 0.78rem;
    color: var(--text-muted, #64748b);
  }

  .stays-gap-dates {
    display: block;
  }

  .stay-form {
    display: flex;
    flex-direction: column;
    gap: 9px;
    margin-top: var(--space-sm, 8px);
    padding: 11px;
    border: 1px solid var(--border, #e2e8f0);
    border-radius: var(--radius-md, 8px);
    background: var(--surface-alt, var(--surface, #fff));
  }

  .stay-form-row {
    display: flex;
    flex-wrap: wrap;
    gap: 9px;
  }

  .stay-field {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    min-width: 160px;
  }

  .stay-field-wide {
    flex-basis: 100%;
  }

  .stay-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted, #64748b);
  }

  .stay-hint {
    font-size: 0.72rem;
    color: var(--text-muted, #64748b);
  }

  .stay-error {
    margin: 0;
    font-size: 0.8rem;
    color: var(--danger, #dc2626);
  }

  .stay-form-actions {
    display: flex;
    gap: 6px;
  }

  .stay-delete {
    margin-left: auto;
    color: var(--danger, #dc2626);
  }

  .stays-add {
    align-self: flex-start;
    margin-top: var(--space-sm, 8px);
  }
</style>
