<script lang="ts">
  import { segmentsApi } from '../api/client';
  import type { SegmentWriteData, SegmentPlaceInput } from '../api/client';
  import type { Trip, Flight, TripSegment, SegmentType } from '../api/types';
  import { splitTransport, toLocalInputValue } from '../lib/utils';
  import { t } from '../lib/i18n';
  import StationInput from './StationInput.svelte';
  import FlightRow from './FlightRow.svelte';
  import SegmentRow from './SegmentRow.svelte';
  import LegDivider from './LegDivider.svelte';
  import ConnectionBadge from './ConnectionBadge.svelte';
  import DateDivider from './DateDivider.svelte';

  interface Props {
    trip: Trip;
    flights: Flight[];
    flightBasePath?: string;
    /** Called after load and after every mutation, so the trip page can feed
     * the map and the day planner without fetching the list a second time. */
    onchange?: (segments: TripSegment[]) => void;
  }

  const { trip, flights, flightBasePath = 'trips', onchange }: Props = $props();

  const TYPES: SegmentType[] = ['train', 'bus', 'ferry', 'car'];

  const TYPE_ICONS: Record<SegmentType, string> = {
    train: '🚆',
    bus: '🚌',
    ferry: '⛴️',
    car: '🚗',
  };

  let segments = $state<TripSegment[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);

  const buckets = $derived(splitTransport(flights, segments));

  interface FormState {
    type: SegmentType;
    departure: SegmentPlaceInput;
    arrival: SegmentPlaceInput;
    departure_datetime: string;
    arrival_datetime: string;
    operator: string;
    number: string;
    booking_reference: string;
    seat: string;
  }

  function emptyForm(): FormState {
    return {
      type: 'train',
      departure: { name: '', lat: null, lon: null },
      arrival: { name: '', lat: null, lon: null },
      departure_datetime: '',
      arrival_datetime: '',
      operator: '',
      number: '',
      booking_reference: '',
      seat: '',
    };
  }

  function formFromSegment(s: TripSegment): FormState {
    return {
      type: s.type,
      departure: { name: s.departure.name, lat: s.departure.lat, lon: s.departure.lon },
      arrival: { name: s.arrival.name, lat: s.arrival.lat, lon: s.arrival.lon },
      // Stored as UTC; the form edits wall-clock time at each station.
      departure_datetime: toLocalInputValue(s.departure_datetime, s.departure.timezone),
      arrival_datetime: toLocalInputValue(s.arrival_datetime, s.arrival.timezone),
      operator: s.operator ?? '',
      number: s.number ?? '',
      booking_reference: s.booking_reference ?? '',
      seat: s.seat ?? '',
    };
  }

  let showForm = $state(false);
  let editingId = $state<string | null>(null);
  let form = $state<FormState>(emptyForm());
  let saving = $state(false);
  let formError = $state<string | null>(null);

  const formValid = $derived(
    form.departure.name.trim().length > 0 &&
      form.arrival.name.trim().length > 0 &&
      form.departure_datetime.length > 0 &&
      form.arrival_datetime.length > 0,
  );

  async function load() {
    try {
      segments = await segmentsApi.list(trip.id);
      loadError = null;
      onchange?.(segments);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  function openAdd() {
    form = emptyForm();
    editingId = null;
    formError = null;
    showForm = true;
  }

  function openEdit(s: TripSegment) {
    form = formFromSegment(s);
    editingId = s.id;
    formError = null;
    showForm = true;
  }

  function closeForm() {
    showForm = false;
    editingId = null;
    formError = null;
  }

  function payload(): SegmentWriteData {
    return {
      type: form.type,
      departure: form.departure,
      arrival: form.arrival,
      departure_datetime: form.departure_datetime,
      arrival_datetime: form.arrival_datetime,
      operator: form.operator.trim() || null,
      number: form.number.trim() || null,
      booking_reference: form.booking_reference.trim() || null,
      seat: form.seat.trim() || null,
    };
  }

  async function save() {
    if (!formValid || saving) return;
    saving = true;
    formError = null;
    try {
      if (editingId) await segmentsApi.update(trip.id, editingId, payload());
      else await segmentsApi.create(trip.id, payload());
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
    const s = segments.find((x) => x.id === editingId);
    if (!s) return;
    const route = `${s.departure.name} → ${s.arrival.name}`;
    if (!confirm($t('segments.delete_confirm', { values: { route } }))) return;
    try {
      await segmentsApi.delete(trip.id, editingId);
      closeForm();
      await load();
    } catch (err) {
      formError = (err as Error).message;
    }
  }
</script>

{#snippet legList(legs: typeof buckets.outbound)}
  {#each legs as leg, i (leg.id)}
    {#if leg.kind === 'flight' && leg.flight}
      <FlightRow flight={leg.flight} basePath={flightBasePath} />
    {:else if leg.segment}
      <SegmentRow segment={leg.segment} onedit={openEdit} />
    {/if}
    {#if i < legs.length - 1}
      {@const prev = legs[i]}
      {@const next = legs[i + 1]}
      {#if prev.arrival_datetime && next.departure_datetime && prev.arrival_datetime.slice(0, 10) !== next.departure_datetime.slice(0, 10)}
        <DateDivider {prev} {next} />
      {:else}
        <ConnectionBadge {prev} {next} />
      {/if}
    {/if}
  {/each}
{/snippet}

{#if loadError}
  <p class="transport-empty" style="color:var(--danger)">{loadError}</p>
{/if}

{#if buckets.hasFlights}
  <LegDivider label={$t('trip.outbound')} legs={buckets.outbound} />
  {@render legList(buckets.outbound)}

  {#if buckets.during.length > 0}
    <LegDivider label={$t('transport.during')} legs={buckets.during} />
    {@render legList(buckets.during)}
  {/if}

  {#if buckets.returning}
    <LegDivider label={$t('trip.return')} legs={buckets.returning} />
    {@render legList(buckets.returning)}
  {/if}
{:else if buckets.outbound.length > 0}
  <!-- Ground legs only: Outbound/Return is a flight-shaped framing and would
       be misleading here, so the list is shown flat. -->
  {@render legList(buckets.outbound)}
{:else if !loading}
  <p class="transport-empty">{$t('segments.empty')}</p>
{/if}

{#if showForm}
  <div class="segment-form">
    <div class="segment-form-row">
      <label class="segment-field">
        <span class="segment-label">{$t('segments.type')}</span>
        <select class="form-input" bind:value={form.type}>
          {#each TYPES as ty}
            <option value={ty}>{TYPE_ICONS[ty]} {$t(`segments.type_${ty}`)}</option>
          {/each}
        </select>
      </label>
      <label class="segment-field">
        <span class="segment-label">{$t('segments.operator')}</span>
        <input class="form-input" type="text" bind:value={form.operator}
               placeholder={$t('segments.operator_placeholder')} />
      </label>
      <label class="segment-field">
        <span class="segment-label">{$t('segments.number')}</span>
        <input class="form-input" type="text" bind:value={form.number}
               placeholder={$t('segments.number_placeholder')} />
      </label>
    </div>

    <div class="segment-form-row">
      <div class="segment-field">
        <span class="segment-label">{$t('segments.from')}</span>
        <StationInput
          value={form.departure.name}
          lat={form.departure.lat ?? null}
          lon={form.departure.lon ?? null}
          kind={form.type}
          placeholder={$t('segments.from_placeholder')}
          onchange={(p) => (form.departure = p)}
        />
      </div>
      <label class="segment-field">
        <span class="segment-label">{$t('segments.departs')}</span>
        <input class="form-input" type="datetime-local" bind:value={form.departure_datetime} />
      </label>
    </div>

    <div class="segment-form-row">
      <div class="segment-field">
        <span class="segment-label">{$t('segments.to')}</span>
        <StationInput
          value={form.arrival.name}
          lat={form.arrival.lat ?? null}
          lon={form.arrival.lon ?? null}
          kind={form.type}
          placeholder={$t('segments.to_placeholder')}
          onchange={(p) => (form.arrival = p)}
        />
      </div>
      <label class="segment-field">
        <span class="segment-label">{$t('segments.arrives')}</span>
        <input class="form-input" type="datetime-local" bind:value={form.arrival_datetime} />
      </label>
    </div>

    <div class="segment-form-row">
      <label class="segment-field">
        <span class="segment-label">{$t('segments.seat')}</span>
        <input class="form-input" type="text" bind:value={form.seat}
               placeholder={$t('segments.seat_placeholder')} />
      </label>
      <label class="segment-field">
        <span class="segment-label">{$t('segments.booking_ref')}</span>
        <input class="form-input" type="text" bind:value={form.booking_reference} />
      </label>
    </div>

    {#if formError}
      <p class="segment-error">{formError}</p>
    {/if}

    <div class="segment-form-actions">
      <button class="btn btn-primary btn-sm" disabled={!formValid || saving} onclick={save}>
        {saving ? $t('segments.saving') : $t('segments.save')}
      </button>
      <button class="btn btn-secondary btn-sm" onclick={closeForm}>{$t('segments.cancel')}</button>
      {#if editingId}
        <button class="btn btn-secondary btn-sm segment-delete" onclick={removeEditing}>
          {$t('segments.delete')}
        </button>
      {/if}
    </div>
  </div>
{:else}
  <button class="btn btn-secondary btn-sm transport-add" onclick={openAdd}>
    + {$t('segments.add')}
  </button>
{/if}

<style>
  .transport-empty {
    font-size: 0.85rem;
    color: var(--text-muted, #64748b);
    margin: 0 0 var(--space-sm, 8px);
  }

  .segment-form {
    display: flex;
    flex-direction: column;
    gap: 9px;
    margin-top: var(--space-sm, 8px);
    padding: 11px;
    border: 1px solid var(--border, #e2e8f0);
    border-radius: var(--radius-md, 8px);
    background: var(--surface-alt, var(--surface, #fff));
  }

  .segment-form-row {
    display: flex;
    flex-wrap: wrap;
    gap: 9px;
  }

  .segment-field {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    min-width: 160px;
  }

  .segment-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted, #64748b);
  }

  .segment-error {
    margin: 0;
    font-size: 0.8rem;
    color: var(--danger, #dc2626);
  }

  .segment-form-actions {
    display: flex;
    gap: 6px;
  }

  .segment-delete {
    margin-left: auto;
    color: var(--danger, #dc2626);
  }

  .transport-add {
    align-self: flex-start;
    margin-top: var(--space-sm, 8px);
  }
</style>
