<script lang="ts">
  import type { Flight, TripSegment, SegmentType, TripStay, StayKind, TripCarRental, PlanItem } from '../api/types';
  import { dayNotesApi, plannerApi } from '../api/client';
  import { serializeDayNote } from '../lib/dayNotes';
  import { staysForDay, rentalsForDay, legRoleFor, localDateKey, type LegRole } from '../lib/utils';
  import { untrack } from 'svelte';
  import { t, locale } from '../lib/i18n';

  interface ChecklistItem {
    text: string;
    checked: boolean;
  }

  export interface DayContent {
    note: string;
    items: ChecklistItem[];
  }

  interface Props {
    tripId: string;
    date: string;
    flights: Flight[];
    segments?: TripSegment[];
    /** Every stay on the trip, not just this day's — the card works out which
     * of them cover this night itself, since a stay spans days. */
    stays?: TripStay[];
    carRentals?: TripCarRental[];
    initialContent: DayContent;
    /** The planner's items on this day. The card's checklist *is* this list
     * (migration 0041 folded the old per-card checklists into it), so adding,
     * ticking or renaming here shows in the planner and the other way round. */
    planItems?: PlanItem[];
    /** The route's cities on this day, the one slept in first; it colours
     * the card the way the planner frames its days. */
    cities?: { id: string; name: string; color: string }[];
    /** The planner's items could not be loaded: show that rather than an
     * empty, editable list that would hide what is really there. */
    itemsUnavailable?: boolean;
    dayNumber?: number;
    /** Kept for callers; the card is always editable now, so these only
     * matter for printing, where the edit controls are hidden by CSS. */
    initiallyExpanded?: boolean;
    forceExpanded?: boolean;
  }

  const {
    tripId,
    date,
    flights,
    segments = [],
    stays = [],
    carRentals = [],
    initialContent,
    planItems = [],
    cities = [],
    dayNumber,
    itemsUnavailable = false,
  }: Props = $props();

  const SEGMENT_ICONS: Record<SegmentType, string> = {
    train: '🚆',
    bus: '🚌',
    ferry: '⛴️',
    car: '🚗',
  };

  const STAY_ICONS: Record<StayKind, string> = {
    hotel: '🏨',
    airbnb: '🏡',
    hostel: '🛏️',
    other: '📍',
  };

  function autogrow(el: HTMLTextAreaElement) {
    const resize = () => { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; };
    resize();
    el.addEventListener('input', resize);
    return { destroy() { el.removeEventListener('input', resize); } };
  }

  // ---- Local state (isolated per card) ----
  // untrack: intentionally snapshot props at mount, changes after mount are ignored
  let note = $state(untrack(() => initialContent.note));
  let items = $state<PlanItem[]>(untrack(() => planItems.map((i) => ({ ...i }))));
  let draft = $state('');
  const isDone = (i: PlanItem) => i.status === 'done';
  const STATUSES: PlanItem['status'][] = ['idea', 'todo', 'booked', 'done'];
  let saving = $state(false);
  let saved = $state(false);

  let pendingTimer: ReturnType<typeof setTimeout> | null = null;

  // ---- Helpers ----

  function formatDayHeader(): string {
    const [y, m, d] = date.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    const loc = $locale ?? undefined;
    const weekday = dt.toLocaleDateString(loc, { weekday: 'short' });
    const month = dt.toLocaleDateString(loc, { month: 'long' });
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/\.$/, '');
    return `${cap(weekday)}, ${d} ${cap(month)}`;
  }

  function formatFlightTime(iso: string | null, tz: string | null): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleTimeString('en-GB', {
        hour: '2-digit', minute: '2-digit', hour12: false,
        timeZone: tz ?? undefined,
      });
    } catch {
      return iso.slice(11, 16);
    }
  }

  /** Flights and ground legs share one chronological list: on a day with both,
   * showing the train after every flight regardless of time would misrepresent
   * the day. Sorted on the real instant, not the printed local time, since the
   * two ends of a day can sit in different zones. */
  interface DayEntry {
    id: string;
    icon: string;
    isFlight: boolean;
    title: string;
    /** "arrives" / "in transit" on the days of a leg that are not its first. */
    note?: string;
    route: string;
    at: number;
  }

  /** A flight's departure_datetime is nullable; such a leg sorts last rather
   * than to the epoch, where it would jump to the top of the day. */
  function instant(iso: string | null | undefined): number {
    if (!iso) return Number.MAX_SAFE_INTEGER;
    const t = new Date(iso).getTime();
    return isNaN(t) ? Number.MAX_SAFE_INTEGER : t;
  }

  /* Two different keys, deliberately. A stay is *banded* onto a day by comparing
   * local calendar dates at the property (staysForDay, on the backend's
   * check_in_date / check_out_date), because a booking's identity is its dates.
   * Its check-in and check-out rows below sort on the real instant, alongside
   * flights, because that is the order the day actually happens in. */
  const stayDay = $derived(staysForDay(stays, date));

  /* Same two-key split as stays: the car is *banded* onto a day by local
   * calendar date, while the counter appointments below sort on the real
   * instant alongside everything else in the day. */
  const rentalDay = $derived(rentalsForDay(carRentals, date));

  /* A leg reaches this card on every day it covers, so the same leg appears on
   * the 31st and the 1st. Its role says which end of it belongs here, and that
   * role also decides where it sorts: a leg you are *arriving* on sits at its
   * arrival time, and a day spent entirely in transit leads the day rather than
   * pretending to happen at the departure time of a previous day. */
  function roleOf(from: string | null, to: string | null): LegRole | null {
    return legRoleFor(date, from, to);
  }

  function roleLabel(role: LegRole): string {
    if (role === 'arrives') return $t('planner.leg_arrives');
    if (role === 'transit') return $t('planner.leg_transit');
    return '';
  }

  const entries = $derived.by((): DayEntry[] => {
    const rows: DayEntry[] = [];

    for (const f of flights) {
      const role =
        roleOf(
          localDateKey(f.departure_datetime, f.departure_timezone),
          localDateKey(f.arrival_datetime, f.arrival_timezone),
        ) ?? 'departs';
      rows.push({
        id: `flight-${f.id}`,
        icon: '✈︎',
        isFlight: true,
        title: f.flight_number,
        note: roleLabel(role),
        route:
          `${f.departure_airport} ${formatFlightTime(f.departure_datetime, f.departure_timezone)}` +
          ` → ${f.arrival_airport} ${formatFlightTime(f.arrival_datetime, f.arrival_timezone)}`,
        at:
          role === 'arrives'
            ? instant(f.arrival_datetime)
            : role === 'transit'
              ? 0
              : instant(f.departure_datetime),
      });
    }

    for (const seg of segments) {
      // Operator and number are both optional, so fall back to the transport
      // type rather than rendering a leg with no label at all.
      const label = [seg.operator, seg.number].filter(Boolean).join(' ');
      const role =
        roleOf(
          localDateKey(seg.departure_datetime, seg.departure.timezone),
          localDateKey(seg.arrival_datetime, seg.arrival.timezone),
        ) ?? 'departs';
      rows.push({
        id: `segment-${seg.id}`,
        icon: SEGMENT_ICONS[seg.type] ?? '🚆',
        isFlight: false,
        title: label || $t(`segments.type_${seg.type}`),
        note: roleLabel(role),
        route:
          `${seg.departure.name} ${formatFlightTime(seg.departure_datetime, seg.departure.timezone)}` +
          ` → ${seg.arrival.name} ${formatFlightTime(seg.arrival_datetime, seg.arrival.timezone)}`,
        at:
          role === 'arrives'
            ? instant(seg.arrival_datetime)
            : role === 'transit'
              ? 0
              : instant(seg.departure_datetime),
      });
    }

    // Check-in and check-out are the day's real events; the nights in between
    // are a state, and show in the header band instead of as rows.
    for (const stay of stayDay.checkIns) {
      rows.push({
        id: `stay-in-${stay.id}`,
        icon: STAY_ICONS[stay.kind] ?? '📍',
        isFlight: false,
        title: $t('stays.check_in'),
        route:
          `${stay.place.name} ${formatFlightTime(stay.check_in_datetime, stay.place.timezone)}`,
        at: instant(stay.check_in_datetime),
      });
    }
    for (const stay of stayDay.checkOuts) {
      rows.push({
        id: `stay-out-${stay.id}`,
        icon: STAY_ICONS[stay.kind] ?? '📍',
        isFlight: false,
        title: $t('stays.check_out'),
        route:
          `${stay.place.name} ${formatFlightTime(stay.check_out_datetime, stay.place.timezone)}`,
        at: instant(stay.check_out_datetime),
      });
    }

    /* Both counter appointments are real events of the day, and both are
     * deadlines — the collection time is binding at most vendors and a late
     * return is charged. The days in between are a state and show in the header
     * band instead, exactly as a stay's nights do. */
    for (const rental of rentalDay.pickups) {
      rows.push({
        id: `rental-in-${rental.id}`,
        icon: '🚗',
        isFlight: false,
        title: $t('car_rentals.pickup_entry', { values: { vendor: rental.vendor } }),
        route:
          `${rental.pickup.name} ${formatFlightTime(rental.pickup_datetime, rental.pickup.timezone)}`,
        at: instant(rental.pickup_datetime),
      });
    }
    for (const rental of rentalDay.dropoffs) {
      rows.push({
        id: `rental-out-${rental.id}`,
        icon: '🚗',
        isFlight: false,
        title: $t('car_rentals.dropoff_entry', { values: { vendor: rental.vendor } }),
        route:
          `${rental.dropoff.name} ${formatFlightTime(rental.dropoff_datetime, rental.dropoff.timezone)}`,
        at: instant(rental.dropoff_datetime),
      });
    }

    return rows.sort((a, b) => a.at - b.at);
  });


  // ---- Mutations ----

  /** The same status dot as the planner: idea → to book → booked → done. */
  async function cycleStatus(item: PlanItem) {
    item.status = STATUSES[(STATUSES.indexOf(item.status) + 1) % STATUSES.length];
    await plannerApi.updateItem(tripId, item.id, { status: item.status }).catch(() => {});
  }

  async function addItem() {
    const title = draft.trim();
    if (!title) return;
    draft = '';
    try {
      const { id } = await plannerApi.createItem(tripId, { title, date, status: 'todo' });
      items = [
        ...items,
        { id, title, date, time: null, notes: null, place_name: null, lat: null, lon: null, status: 'todo', sort_order: items.length },
      ];
    } catch {
      draft = title;
    }
  }

  async function renameItem(item: PlanItem, el: HTMLTextAreaElement) {
    const clean = el.value.trim();
    // Clearing the text is not a delete — that is the ✕ — so put it back.
    if (!clean) {
      el.value = item.title;
      return;
    }
    if (clean === item.title) return;
    item.title = clean;
    await plannerApi.updateItem(tripId, item.id, { title: clean }).catch(() => {});
  }

  async function deleteItem(item: PlanItem) {
    items = items.filter((i) => i.id !== item.id);
    await plannerApi.deleteItem(tripId, item.id).catch(() => {});
  }

  function onNoteInput(value: string) {
    note = value;
    scheduleSave();
  }

  // ---- Autosave ----

  function scheduleSave() {
    if (pendingTimer) clearTimeout(pendingTimer);
    pendingTimer = setTimeout(() => {
      pendingTimer = null;
      doSave();
    }, 600);
  }

  async function doSave() {
    saving = true;
    try {
      await dayNotesApi.upsert(tripId, date, serializeDayNote(note, initialContent.items));
      saved = true;
      setTimeout(() => { saved = false; }, 1500);
    } catch {
      // silent — retry on next change
    } finally {
      saving = false;
    }
  }
</script>

<div class="day-card" style={cities[0] ? `--frame:${cities[0].color}` : ''}>
  <header class="dc-head">
    <div class="dc-when">
      {#if dayNumber}<span class="dc-num">{$t('planner.day_prefix')} {dayNumber}</span>{/if}
      <span class="dc-date">{formatDayHeader()}</span>
    </div>
    <div class="dc-cities">
      {#each cities as c (c.id)}
        <span class="dc-city" style="--stop:{c.color}">{c.name}</span>
      {/each}
    </div>
    {#if saving}
      <span class="save-status saving">{$t('planner.saving')}</span>
    {:else if saved}
      <span class="save-status saved">✓</span>
    {/if}
  </header>

  {#if entries.length > 0}
    <div class="dc-section">
      {#each entries as entry (entry.id)}
        <!-- day-flight-row / day-stay-band: the names the E2E specs select on. -->
        <div class="dc-move day-flight-row">
          <span class="dc-icon">{entry.icon}</span>
          <span>
            <strong>{entry.title}</strong>
            {#if entry.note}<span class="dc-move-note">{entry.note}</span>{/if}
            {entry.route}
          </span>
        </div>
      {/each}
    </div>
  {/if}

  {#if stayDay.nights.length > 0 || rentalDay.held.length > 0}
    <div class="dc-section">
      {#each stayDay.nights as n (n.stay.id)}
        <div class="dc-stay day-stay-band">
          {STAY_ICONS[n.stay.kind] ?? '📍'} {n.stay.place.name}
          <span class="dc-stay-night">{$t('stays.night_of', { values: { night: n.night, nights: n.nights } })}</span>
        </div>
      {/each}
      {#each rentalDay.held as h (h.rental.id)}
        <div class="dc-stay day-stay-band">
          🚗 {h.rental.vendor}
          <span class="dc-stay-night">{$t('car_rentals.day_of', { values: { day: h.day, days: h.days } })}</span>
        </div>
      {/each}
    </div>
  {/if}

  {#if itemsUnavailable}
    <div class="dc-section dc-unavailable">{$t('planner.items_unavailable')}</div>
  {:else}
  <div class="dc-section dc-items">
    {#each items as item (item.id)}
      <div class="dc-item status-{item.status}">
        <button
          class="dc-dot"
          title={$t(`organizer.status_${item.status}`)}
          aria-label={$t(`organizer.status_${item.status}`)}
          onclick={() => cycleStatus(item)}
        ></button>
        <div class="dc-item-body">
          <div class="dc-item-line">
            {#if item.time}<span class="dc-time">{item.time}</span>{/if}
            <textarea
              class="dc-title"
              class:done={isDone(item)}
              rows={1}
              value={item.title}
              use:autogrow
              aria-label={$t('organizer.item_title')}
              onblur={(e) => renameItem(item, e.currentTarget as HTMLTextAreaElement)}
            ></textarea>
          </div>
          {#if item.place_name}<span class="dc-place">📍 {item.place_name}</span>{/if}
        </div>
        <button class="dc-delete" onclick={() => deleteItem(item)} aria-label={$t('planner.delete_item')}>✕</button>
      </div>
    {/each}
    <!-- A form rather than a keydown on Enter: some phone keyboards report
         the key as "Unidentified", while their Done/Go button always submits. -->
    <form class="dc-add-form" onsubmit={(e) => { e.preventDefault(); addItem(); }}>
      <input
        class="dc-add"
        placeholder={$t('organizer.add_item')}
        bind:value={draft}
        enterkeyhint="done"
        onblur={addItem}
      />
    </form>
  </div>
  {/if}

  <textarea
    class="dc-note"
    placeholder={$t('planner.note_placeholder')}
    value={note}
    rows={1}
    use:autogrow
    oninput={(e) => onNoteInput((e.currentTarget as HTMLTextAreaElement).value)}
  ></textarea>
</div>

<style>
  .day-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 5px solid var(--frame, var(--border));
    border-radius: var(--radius-md);
    overflow: hidden;
  }
  .dc-head {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: 8px 12px;
    background: color-mix(in srgb, var(--frame, transparent) 12%, var(--bg-card));
  }
  .dc-when {
    display: flex;
    flex-direction: column;
  }
  .dc-num {
    font-size: 0.7rem;
    color: var(--text-muted);
  }
  .dc-date {
    font-weight: 700;
  }
  .dc-cities {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    flex: 1;
    justify-content: flex-end;
  }
  .dc-city {
    font-size: 0.78rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--stop) 18%, transparent);
    border-left: 3px solid var(--stop);
  }
  .save-status { font-size: 0.72rem; }
  .save-status.saving { color: var(--text-muted); }
  .save-status.saved { color: var(--success, #16a34a); font-weight: 600; }

  .dc-section {
    padding: 6px 12px;
    border-top: 1px solid var(--border-light, var(--border));
    font-size: 0.85rem;
  }
  .dc-move,
  .dc-stay {
    display: flex;
    gap: 6px;
    padding: 3px 0;
    line-height: 1.35;
  }
  .dc-move-note,
  .dc-stay-night {
    color: var(--text-muted);
    font-size: 0.78rem;
    margin: 0 4px;
  }
  .dc-unavailable {
    color: var(--warning-text, var(--warning));
  }
  .dc-items {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-top: 8px;
    padding-bottom: 8px;
  }
  .dc-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 8px;
    border-radius: var(--radius-sm);
    background: var(--bg-subtle, var(--surface-alt));
    border: 1px solid var(--border-light, var(--border));
  }
  .dc-dot {
    flex: none;
    width: 16px;
    height: 16px;
    margin-top: 3px;
    border-radius: 50%;
    border: 2px solid var(--text-muted);
    background: transparent;
    padding: 0;
    cursor: pointer;
  }
  .status-todo .dc-dot { border-color: var(--warning); }
  .status-booked .dc-dot { border-color: var(--success); background: var(--success); }
  .status-done .dc-dot { border-color: var(--text-muted); background: var(--text-muted); }
  .dc-item-body {
    flex: 1;
    min-width: 0;
  }
  .dc-item-line {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .dc-time {
    font-family: var(--font-mono);
    font-size: 0.85rem;
    color: var(--text-secondary);
  }
  .dc-title {
    flex: 1;
    min-width: 0;
    font: inherit;
    font-size: 16px; /* iOS zooms in on anything smaller */
    line-height: 1.3;
    border: none;
    background: transparent;
    color: var(--text-primary);
    resize: none;
    padding: 0;
    overflow: hidden;
  }
  .dc-title:focus { outline: none; }
  .dc-title.done { text-decoration: line-through; color: var(--text-muted); }
  .dc-place {
    display: block;
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-top: 2px;
  }
  .dc-delete {
    flex: none;
    border: none;
    background: none;
    color: var(--text-muted);
    font-size: 0.8rem;
    padding: 4px;
    cursor: pointer;
  }
  .dc-delete:hover { color: var(--danger, #dc2626); }
  .dc-add {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: 16px;
    padding: 7px 10px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-primary);
  }
  .dc-add:focus,
  .dc-note:focus {
    outline: none;
    border-color: var(--accent);
  }
  .dc-note {
    display: block;
    width: 100%;
    box-sizing: border-box;
    min-height: 40px;
    font: inherit;
    font-size: 16px;
    padding: 8px 12px;
    border: none;
    border-top: 1px solid var(--border-light, var(--border));
    background: transparent;
    color: var(--text-primary);
    resize: none;
  }

  @media (max-width: 640px) {
    .dc-head { padding: 6px 10px; }
    .dc-section { padding: 6px 10px; }
    .dc-items { padding-top: 6px; padding-bottom: 6px; }
    .dc-item { padding: 5px 6px; gap: 6px; }
    .dc-note { padding: 8px 10px; }
  }

  @media print {
    .save-status,
    .dc-add,
    .dc-delete { display: none !important; }
    .dc-note:placeholder-shown { display: none; }
    .day-card { break-inside: avoid; border: 1px solid #ccc; border-left: 5px solid var(--frame, #ccc); }
  }
  .dc-add-form {
    display: contents;
  }
</style>
