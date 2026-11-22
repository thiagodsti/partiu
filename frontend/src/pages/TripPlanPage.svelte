<script lang="ts">
  /* The trip organizer. The route of cities sits on top; below it, a calendar
   * of the trip's days (city, transport, stay and plan at a glance), the
   * selected day in detail, and a map of everything that has a place, which
   * follows the selected day.
   *
   * Flights, ground legs, stays and day notes are read from the features that
   * own them, so a booking imported from mail shows up here without being
   * copied. Only the route, the plan items and the to-dos are the organizer's
   * own (see backend/planner). */
  import { t } from '../lib/i18n';
  import {
    tripsApi,
    segmentsApi,
    staysApi,
    dayNotesApi,
    expensesApi,
    plannerApi,
  } from '../api/client';
  import type {
    Trip,
    Flight,
    TripSegment,
    TripStay,
    Participant,
    PlanStop,
    PlanItem,
    PlanItemStatus,
    PlanTask,
    PickedPlace,
  } from '../api/types';
  import PlaceInput from '../components/PlaceInput.svelte';
  import PlanMap, { type MapCity, type MapLine, type MapPoint } from '../components/PlanMap.svelte';
  import { formatTime, localDateKey } from '../lib/utils';
  import { toasts } from '../lib/toastStore';

  interface Props {
    params: { id: string };
  }
  const { params }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let trip = $state<Trip | null>(null);
  let segments = $state<TripSegment[]>([]);
  let stays = $state<TripStay[]>([]);
  let people = $state<Participant[]>([]);
  let stops = $state<PlanStop[]>([]);
  let items = $state<PlanItem[]>([]);
  let tasks = $state<PlanTask[]>([]);
  let notes = $state<Record<string, string>>({});
  let selected = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [tr, segs, sts, plan, dn, ppl] = await Promise.all([
        tripsApi.get(params.id),
        segmentsApi.list(params.id).catch(() => [] as TripSegment[]),
        staysApi.list(params.id).catch(() => [] as TripStay[]),
        plannerApi.get(params.id),
        dayNotesApi.list(params.id).catch(() => []),
        expensesApi.participants(params.id).catch(() => [] as Participant[]),
      ]);
      trip = tr;
      segments = segs;
      stays = sts;
      stops = plan.stops;
      items = plan.items;
      tasks = plan.tasks;
      people = ppl;
      notes = Object.fromEntries(dn.map((n) => [n.date, n.content]));
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }
  load();

  // ---- Days ---------------------------------------------------------------

  function addDays(iso: string, n: number): string {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
  }

  /** Every day from the trip's first to its last, widened by the route so a
   * trip planned before any flight still gets a calendar. */
  const days = $derived.by<string[]>(() => {
    const bounds = [
      trip?.start_date ?? trip?.planned_start_date,
      trip?.end_date ?? trip?.planned_end_date,
      ...stops.flatMap((s) => [s.start_date, s.end_date]),
    ].filter((d): d is string => !!d);
    if (bounds.length === 0) return [];
    bounds.sort();
    const out: string[] = [];
    for (let d = bounds[0]; d <= bounds[bounds.length - 1] && out.length < 400; d = addDays(d, 1)) {
      out.push(d);
    }
    return out;
  });

  $effect(() => {
    if (days.length && (!selected || !days.includes(selected))) selected = days[0];
  });

  /** Calendar cells, Monday first, with blanks before the first day. */
  const cells = $derived.by<(string | null)[]>(() => {
    if (!days.length) return [];
    const lead = (new Date(`${days[0]}T12:00:00`).getDay() + 6) % 7;
    return [...Array<null>(lead).fill(null), ...days];
  });

  const COLORS = ['#e76f51', '#2a9d8f', '#e9a03b', '#8e7dbe', '#d1495b', '#457b9d', '#6a994e', '#c97c5d'];
  const stopColor = (s: PlanStop) => COLORS[Math.max(0, stops.indexOf(s)) % COLORS.length];

  /** Where you sleep on `date`: the stop whose nights cover it. */
  function nightStop(date: string): PlanStop | undefined {
    return stops.find((s) => s.start_date <= date && date < s.end_date);
  }
  /** Where the day starts, when that differs from where it ends (a travel day). */
  function morningStop(date: string): PlanStop | undefined {
    const prev = nightStop(addDays(date, -1));
    return prev && prev !== nightStop(date) ? prev : undefined;
  }

  function nightsOf(s: PlanStop): number {
    return Math.round((Date.parse(s.end_date) - Date.parse(s.start_date)) / 86_400_000);
  }

  const flights = $derived<Flight[]>(trip?.flights ?? []);

  interface Move {
    key: string;
    icon: string;
    label: string;
    time: string;
    sort: string;
  }

  function movesOn(date: string): Move[] {
    const out: Move[] = [];
    for (const f of flights) {
      if (localDateKey(f.departure_datetime, f.departure_timezone) !== date) continue;
      out.push({
        key: `f-${f.id}`,
        icon: '✈️',
        label: `${f.flight_number} ${f.departure_airport}→${f.arrival_airport}`,
        time: formatTime(f.departure_datetime, f.departure_timezone),
        sort: f.departure_datetime ?? '',
      });
    }
    for (const s of segments) {
      if (localDateKey(s.departure_datetime, s.departure.timezone) !== date) continue;
      out.push({
        key: `s-${s.id}`,
        icon: { train: '🚆', bus: '🚌', ferry: '⛴️', car: '🚗' }[s.type] ?? '→',
        label: `${s.departure.name} → ${s.arrival.name}`,
        time: formatTime(s.departure_datetime, s.departure.timezone),
        sort: s.departure_datetime,
      });
    }
    return out.sort((a, b) => a.sort.localeCompare(b.sort));
  }

  function stayFor(date: string): TripStay | undefined {
    return stays.find((s) => s.check_in_date <= date && date < s.check_out_date);
  }

  /** A night of the trip with no booking: not the last day, and not a night
   * spent on a flight that lands the next day. */
  function missingStay(date: string): boolean {
    if (date === days[days.length - 1] || stayFor(date)) return false;
    return !flights.some(
      (f) =>
        localDateKey(f.departure_datetime, f.departure_timezone) === date &&
        localDateKey(f.arrival_datetime, f.arrival_timezone) !== date,
    );
  }

  const missingNights = $derived(days.filter(missingStay).length);

  const fmt = (date: string, opts: Intl.DateTimeFormatOptions) => {
    const s = new Date(`${date}T12:00:00`).toLocaleDateString(undefined, opts);
    return s.charAt(0).toUpperCase() + s.slice(1);
  };
  const isWeekend = (date: string) => [0, 6].includes(new Date(`${date}T12:00:00`).getDay());

  // ---- Route ----------------------------------------------------------------

  let stopForm = $state<{ id: string | null; place: PickedPlace; start: string; end: string } | null>(null);

  function emptyPlace(name = ''): PickedPlace {
    return { name, lat: null, lon: null, country_code: null, address: null };
  }

  function openNewStop() {
    const last = stops[stops.length - 1];
    const start = last?.end_date ?? days[0] ?? new Date().toISOString().slice(0, 10);
    stopForm = { id: null, place: emptyPlace(), start, end: addDays(start, 2) };
  }

  function openStop(s: PlanStop) {
    stopForm = {
      id: s.id,
      place: { ...emptyPlace(s.name), lat: s.lat, lon: s.lon, country_code: s.country_code },
      start: s.start_date,
      end: s.end_date,
    };
    selected = s.start_date;
  }

  async function saveStop() {
    if (!stopForm || !stopForm.place.name.trim()) return;
    const data = {
      name: stopForm.place.name.trim(),
      lat: stopForm.place.lat,
      lon: stopForm.place.lon,
      country_code: stopForm.place.country_code ?? null,
      start_date: stopForm.start,
      end_date: stopForm.end,
    };
    try {
      if (stopForm.id) await plannerApi.updateStop(params.id, stopForm.id, data);
      else await plannerApi.createStop(params.id, data);
      stopForm = null;
      stops = (await plannerApi.get(params.id)).stops;
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function deleteStop() {
    const id = stopForm?.id;
    if (!id) return;
    await plannerApi.deleteStop(params.id, id);
    stops = stops.filter((s) => s.id !== id);
    stopForm = null;
  }

  // ---- Items ----------------------------------------------------------------

  const STATUSES: PlanItemStatus[] = ['idea', 'todo', 'booked', 'done'];

  function itemsOn(date: string | null): PlanItem[] {
    return items
      .filter((i) => i.date === date)
      .sort((a, b) => a.sort_order - b.sort_order || (a.time ?? '').localeCompare(b.time ?? ''));
  }

  let dayDraft = $state('');
  let ideaDraft = $state('');

  /** "07:20 Muralha" sets the time; everything else is the title. */
  function parseDraft(raw: string): { title: string; time: string | null } {
    const m = raw.trim().match(/^(\d{1,2})[:h](\d{2})\s+(.+)$/);
    if (m && Number(m[1]) < 24 && Number(m[2]) < 60) {
      return { time: `${m[1].padStart(2, '0')}:${m[2]}`, title: m[3] };
    }
    return { time: null, title: raw.trim() };
  }

  async function addItem(date: string | null) {
    const raw = date ? dayDraft : ideaDraft;
    if (!raw.trim()) return;
    if (date) dayDraft = '';
    else ideaDraft = '';
    const { title, time } = parseDraft(raw);
    const status: PlanItemStatus = date ? 'todo' : 'idea';
    try {
      const { id } = await plannerApi.createItem(params.id, { title, time, date, status });
      items = [
        ...items,
        { id, title, time, date, notes: null, place_name: null, lat: null, lon: null, status, sort_order: itemsOn(date).length },
      ];
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function cycleStatus(item: PlanItem) {
    const next = STATUSES[(STATUSES.indexOf(item.status) + 1) % STATUSES.length];
    item.status = next;
    await plannerApi.updateItem(params.id, item.id, { status: next });
  }

  let editing = $state<PlanItem | null>(null);

  async function saveEditing() {
    if (!editing) return;
    const e = { ...editing, time: editing.time || null };
    const idx = items.findIndex((i) => i.id === e.id);
    if (idx >= 0) items[idx] = e;
    editing = null;
    try {
      await plannerApi.updateItem(params.id, e.id, {
        title: e.title,
        time: e.time,
        notes: e.notes,
        status: e.status,
        date: e.date,
        place_name: e.place_name || null,
        lat: e.lat,
        lon: e.lon,
      });
    } catch (err) {
      toasts.show((err as Error).message, 'error');
      load();
    }
  }

  async function deleteItem(item: PlanItem) {
    items = items.filter((i) => i.id !== item.id);
    editing = null;
    await plannerApi.deleteItem(params.id, item.id);
  }

  // Dragging a plan item: onto a calendar day, into the day list at a
  // position, or back to the ideas.
  let dragId = $state<string | null>(null);
  let dropTarget = $state<string | null>(null);
  const IDEAS = '__ideas__';

  async function dropOn(date: string | null, beforeId: string | null = null) {
    const id = dragId;
    dragId = null;
    dropTarget = null;
    const moving = items.find((i) => i.id === id);
    if (!moving) return;
    const list = itemsOn(date).filter((i) => i.id !== id);
    const at = beforeId ? list.findIndex((i) => i.id === beforeId) : -1;
    list.splice(at < 0 ? list.length : at, 0, moving);
    const changes: Promise<unknown>[] = [];
    list.forEach((it, order) => {
      const dateChanged = it.id === moving.id && it.date !== date;
      if (it.sort_order === order && !dateChanged) return;
      const patch: Partial<PlanItem> = { sort_order: order };
      if (dateChanged) patch.date = date;
      it.sort_order = order;
      if (dateChanged) it.date = date;
      changes.push(plannerApi.updateItem(params.id, it.id, patch));
    });
    items = [...items];
    try {
      await Promise.all(changes);
    } catch (err) {
      toasts.show((err as Error).message, 'error');
      load();
    }
  }

  function overHandler(target: string) {
    return (e: DragEvent) => {
      if (!dragId) return;
      e.preventDefault();
      dropTarget = target;
    };
  }
  function leaveHandler(target: string) {
    return () => {
      if (dropTarget === target) dropTarget = null;
    };
  }

  // ---- Day notes --------------------------------------------------------------

  async function saveNote(date: string, content: string) {
    if ((notes[date] ?? '') === content) return;
    notes[date] = content;
    await dayNotesApi.upsert(params.id, date, content);
  }

  // ---- Tasks ------------------------------------------------------------------

  let sideTab = $state<'ideas' | 'tasks'>('ideas');
  let taskDraft = $state('');
  const personKey = (type: string | null, id: number | null) => (type && id != null ? `${type}:${id}` : '');

  async function addTask() {
    const text = taskDraft.trim();
    if (!text) return;
    taskDraft = '';
    const { id } = await plannerApi.createTask(params.id, { text });
    tasks = [...tasks, { id, text, done: false, assignee_type: null, assignee_id: null, sort_order: tasks.length }];
  }

  async function toggleTask(task: PlanTask) {
    task.done = !task.done;
    await plannerApi.updateTask(params.id, task.id, { done: task.done });
  }

  async function assign(task: PlanTask, key: string) {
    const [type, id] = key ? key.split(':') : [null, null];
    task.assignee_type = (type as 'user' | 'guest' | null) ?? null;
    task.assignee_id = id ? Number(id) : null;
    try {
      await plannerApi.updateTask(params.id, task.id, {
        assignee_type: task.assignee_type,
        assignee_id: task.assignee_id,
      });
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function deleteTask(task: PlanTask) {
    tasks = tasks.filter((x) => x.id !== task.id);
    await plannerApi.deleteTask(params.id, task.id);
  }

  const openTasks = $derived(tasks.filter((x) => !x.done).length);

  // ---- Map --------------------------------------------------------------------

  const mapCities = $derived<MapCity[]>(
    stops
      .map((s, i) => ({ s, i }))
      .filter(({ s }) => s.lat != null && s.lon != null)
      .map(({ s, i }) => ({
        name: s.name,
        lat: s.lat as number,
        lon: s.lon as number,
        color: stopColor(s),
        order: i + 1,
        nights: nightsOf(s),
      })),
  );

  const mapPoints = $derived.by<MapPoint[]>(() => {
    const out: MapPoint[] = [];
    const sel = selected;
    for (const s of stays) {
      if (s.place.lat == null || s.place.lon == null) continue;
      out.push({
        id: `stay-${s.id}`,
        kind: 'stay',
        title: s.place.name,
        lat: s.place.lat,
        lon: s.place.lon,
        active: !!sel && s.check_in_date <= sel && sel < s.check_out_date,
      });
    }
    const byDay = new Map<string, number>();
    for (const it of [...items].sort((a, b) => a.sort_order - b.sort_order)) {
      const key = it.date ?? '';
      byDay.set(key, (byDay.get(key) ?? 0) + 1);
      if (it.lat == null || it.lon == null) continue;
      const city = it.date ? nightStop(it.date) ?? morningStop(it.date) : undefined;
      out.push({
        id: it.id,
        kind: 'item',
        title: it.time ? `${it.time} ${it.title}` : it.title,
        lat: it.lat,
        lon: it.lon,
        active: it.date === sel,
        color: city ? stopColor(city) : '#64748b',
        label: it.date === sel ? String(byDay.get(key)) : '',
      });
    }
    return out;
  });

  const mapLines = $derived<MapLine[]>(
    segments
      .filter((s) => s.departure.lat != null && s.arrival.lat != null)
      .map((s) => ({
        id: s.id,
        from: [s.departure.lat as number, s.departure.lon as number] as [number, number],
        to: [s.arrival.lat as number, s.arrival.lon as number] as [number, number],
        color: '#10b981',
      })),
  );

  /** Showing the whole route rather than following the selected day. */
  let overview = $state(false);
  $effect(() => {
    void selected;
    overview = false;
  });

  /** The selected day's places, or the city it is in when none has one. */
  const mapFocus = $derived.by<[number, number][]>(() => {
    if (!selected || overview) return [];
    const active = mapPoints.filter((p) => p.active).map((p) => [p.lat, p.lon] as [number, number]);
    if (active.length) return active;
    const city = nightStop(selected) ?? morningStop(selected);
    return city && city.lat != null && city.lon != null ? [[city.lat, city.lon]] : [];
  });

  function pointClicked(p: MapPoint) {
    const it = items.find((i) => i.id === p.id);
    if (it) {
      if (it.date) selected = it.date;
      editing = { ...it };
    }
  }

  function cityClicked(name: string) {
    const s = stops.find((x) => x.name === name);
    if (s) selected = s.start_date;
  }

  /** The number an item carries on the map, when it has a place there. */
  function mapNumber(item: PlanItem, date: string | null): number {
    if (!date || item.lat == null) return 0;
    return itemsOn(date).indexOf(item) + 1;
  }
</script>

<div class="planner-page">
  {#if loading}
    <p class="muted">{$t('planner.loading')}</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else if trip}
    <header class="plan-header">
      <div>
        <a href="#/trips/{params.id}" class="back">← {trip.name}</a>
        <h1>{$t('organizer.title')}</h1>
      </div>
      <div class="stats">
        <span><strong>{days.length}</strong> {$t('organizer.days')}</span>
        <span><strong>{stops.length}</strong> {$t('organizer.cities')}</span>
        <span class:warn={missingNights > 0}><strong>{missingNights}</strong> {$t('organizer.nights_without_stay')}</span>
        <span><strong>{openTasks}</strong> {$t('organizer.open_tasks')}</span>
      </div>
    </header>

    <!-- Route -->
    <section class="route" aria-label={$t('organizer.route')}>
      <div class="route-chips">
        {#each stops as stop, i (stop.id)}
          {#if i > 0}<span class="route-arrow">→</span>{/if}
          <button class="stop-chip" style="--stop:{stopColor(stop)}" onclick={() => openStop(stop)}>
            <span class="stop-num">{i + 1}</span>
            <span class="stop-name">{stop.name}</span>
            <span class="stop-dates">{fmt(stop.start_date, { day: 'numeric', month: 'short' })} – {fmt(stop.end_date, { day: 'numeric', month: 'short' })} · {$t('organizer.nights', { values: { n: nightsOf(stop) } })}</span>
          </button>
        {/each}
        <button class="btn btn-secondary btn-sm" data-testid="add-stop" onclick={openNewStop}>+ {$t('organizer.add_city')}</button>
      </div>

      {#if stopForm}
        <form class="stop-form" onsubmit={(e) => { e.preventDefault(); saveStop(); }}>
          <div class="field grow">
            <span class="form-label">{$t('organizer.city')}</span>
            <PlaceInput
              kind="city"
              value={stopForm.place.name}
              lat={stopForm.place.lat}
              lon={stopForm.place.lon}
              placeholder="Beijing"
              onchange={(p) => { if (stopForm) stopForm.place = p; }}
            />
          </div>
          <label class="field">
            <span class="form-label">{$t('organizer.arrive')}</span>
            <input class="form-input" type="date" bind:value={stopForm.start} required />
          </label>
          <label class="field">
            <span class="form-label">{$t('organizer.leave')}</span>
            <input class="form-input" type="date" bind:value={stopForm.end} min={stopForm.start} required />
          </label>
          <div class="form-actions">
            <button class="btn btn-primary btn-sm" type="submit">{$t('organizer.save')}</button>
            {#if stopForm.id}
              <button class="btn btn-danger btn-sm" type="button" onclick={deleteStop}>{$t('organizer.remove')}</button>
            {/if}
            <button class="btn btn-secondary btn-sm" type="button" onclick={() => (stopForm = null)}>{$t('organizer.cancel')}</button>
          </div>
        </form>
      {/if}
    </section>

    <div class="workspace">
      <div class="main-col">
        {#if days.length === 0}
          <p class="muted empty">{$t('organizer.no_days')}</p>
        {:else}
          <!-- Calendar -->
          <div class="calendar">
            {#each [0, 1, 2, 3, 4, 5, 6] as i (i)}
              <div class="cal-weekday">{fmt(addDays('2027-03-01', i), { weekday: 'short' })}</div>
            {/each}
            {#each cells as date, i (date ?? `blank-${i}`)}
              {#if date === null}
                <div class="cal-blank"></div>
              {:else}
                {@const night = nightStop(date)}
                {@const morning = morningStop(date)}
                {@const moves = movesOn(date)}
                {@const stay = stayFor(date)}
                {@const count = itemsOn(date).length}
                <button
                  class="day"
                  class:selected={selected === date}
                  class:weekend={isWeekend(date)}
                  class:drop={dropTarget === date}
                  style="--stop:{night ? stopColor(night) : morning ? stopColor(morning) : 'var(--border)'}"
                  onclick={() => (selected = date)}
                  ondragover={overHandler(date)}
                  ondragleave={leaveHandler(date)}
                  ondrop={(e) => { e.preventDefault(); dropOn(date); }}
                >
                  <span class="day-top">
                    <span class="day-date">{fmt(date, { day: 'numeric', month: 'short' })}</span>
                    <span class="day-n">{$t('planner.day_prefix')} {days.indexOf(date) + 1}</span>
                  </span>
                  <span class="day-city">
                    {#if morning && night}{morning.name} → {night.name}{:else if night}{night.name}{:else if morning}{morning.name}{:else}&nbsp;{/if}
                  </span>
                  <span class="day-icons">
                    {#each moves.slice(0, 2) as m (m.key)}<span title={m.label}>{m.icon}</span>{/each}
                    {#if stay}<span title={stay.place.name}>🏨</span>{:else if missingStay(date)}<span class="warn-ic" title={$t('organizer.no_stay')}>⚠</span>{/if}
                    {#if count}<span class="day-count">{count}</span>{/if}
                  </span>
                </button>
              {/if}
            {/each}
          </div>

          <!-- Selected day -->
          {#if selected}
            {@const sel = selected}
            {@const night = nightStop(sel)}
            {@const morning = morningStop(sel)}
            {@const stay = stayFor(sel)}
            {@const moves = movesOn(sel)}
            <section class="day-panel">
              <header class="day-panel-head" style="--stop:{night ? stopColor(night) : morning ? stopColor(morning) : 'var(--border)'}">
                <div>
                  <span class="dp-weekday">{$t('planner.day_prefix')} {days.indexOf(sel) + 1} · {fmt(sel, { weekday: 'long' })}</span>
                  <h2>
                    {fmt(sel, { day: 'numeric', month: 'long' })}
                    {#if morning && night}· {morning.name} → {night.name}{:else if night || morning}· {(night ?? morning)?.name}{/if}
                  </h2>
                </div>
                <div class="dp-nav">
                  <button class="btn btn-secondary btn-sm" disabled={days.indexOf(sel) === 0} onclick={() => (selected = addDays(sel, -1))} aria-label={$t('organizer.prev_day')}>←</button>
                  <button class="btn btn-secondary btn-sm" disabled={days.indexOf(sel) === days.length - 1} onclick={() => (selected = addDays(sel, 1))} aria-label={$t('organizer.next_day')}>→</button>
                </div>
              </header>

              {#if moves.length || stay || missingStay(sel)}
                <div class="facts">
                  {#each moves as m (m.key)}
                    <div class="fact"><span>{m.icon}</span><span class="mono">{m.time}</span><span>{m.label}</span></div>
                  {/each}
                  {#if stay}
                    <div class="fact"><span>🏨</span><span>{stay.place.name}</span></div>
                  {:else if missingStay(sel)}
                    <div class="fact warn-text"><span>⚠</span><span>{$t('organizer.no_stay')}</span></div>
                  {/if}
                </div>
              {/if}

              <div
                class="day-items"
                class:drop={dropTarget === `list-${sel}`}
                role="list"
                ondragover={overHandler(`list-${sel}`)}
                ondragleave={leaveHandler(`list-${sel}`)}
                ondrop={(e) => { e.preventDefault(); dropOn(sel); }}
              >
                {#each itemsOn(sel) as item (item.id)}
                  {@render planItem(item, sel)}
                {/each}
                <input
                  class="item-draft"
                  placeholder={$t('organizer.add_item')}
                  bind:value={dayDraft}
                  onkeydown={(e) => { if (e.key === 'Enter') addItem(sel); }}
                />
              </div>

              <textarea
                class="note"
                rows="2"
                placeholder={$t('organizer.note_placeholder')}
                value={notes[sel] ?? ''}
                onblur={(e) => saveNote(sel, (e.currentTarget as HTMLTextAreaElement).value)}
              ></textarea>
            </section>
          {/if}
        {/if}
      </div>

      <aside class="side">
        <div class="map-box">
          <button class="map-overview btn btn-secondary btn-sm" class:active={overview} onclick={() => (overview = true)}>🗺 {$t('organizer.whole_route')}</button>
          <PlanMap cities={mapCities} points={mapPoints} lines={mapLines} focus={mapFocus} onCityClick={cityClicked} onPointClick={pointClicked} />
        </div>

        <section class="panel">
          <div class="tabs" role="tablist">
            <button role="tab" class:active={sideTab === 'ideas'} aria-selected={sideTab === 'ideas'} onclick={() => (sideTab = 'ideas')}>💡 {$t('organizer.ideas')} <span class="badge">{itemsOn(null).length}</span></button>
            <button role="tab" class:active={sideTab === 'tasks'} aria-selected={sideTab === 'tasks'} onclick={() => (sideTab = 'tasks')}>✅ {$t('organizer.before_trip')} <span class="badge">{openTasks}</span></button>
          </div>

          {#if sideTab === 'ideas'}
            <div
              class="tab-body"
              class:drop={dropTarget === IDEAS}
              role="list"
              ondragover={overHandler(IDEAS)}
              ondragleave={leaveHandler(IDEAS)}
              ondrop={(e) => { e.preventDefault(); dropOn(null); }}
            >
              <p class="hint">{$t('organizer.ideas_hint')}</p>
              {#each itemsOn(null) as item (item.id)}
                {@render planItem(item, null)}
              {/each}
              <input
                class="item-draft"
                placeholder={$t('organizer.add_idea')}
                bind:value={ideaDraft}
                onkeydown={(e) => { if (e.key === 'Enter') addItem(null); }}
              />
            </div>
          {:else}
            <div class="tab-body">
              {#each tasks as task (task.id)}
                <div class="task" class:done={task.done}>
                  <input type="checkbox" checked={task.done} onchange={() => toggleTask(task)} />
                  <span class="task-text">{task.text}</span>
                  <select class="assignee" value={personKey(task.assignee_type, task.assignee_id)} onchange={(e) => assign(task, (e.currentTarget as HTMLSelectElement).value)}>
                    <option value="">—</option>
                    {#each people as p (personKey(p.type, p.id))}
                      <option value={personKey(p.type, p.id)}>{p.name}</option>
                    {/each}
                  </select>
                  <button class="icon-btn" aria-label={$t('organizer.remove')} onclick={() => deleteTask(task)}>×</button>
                </div>
              {/each}
              <input class="item-draft" placeholder={$t('organizer.add_task')} bind:value={taskDraft} onkeydown={(e) => { if (e.key === 'Enter') addTask(); }} />
            </div>
          {/if}
        </section>
      </aside>
    </div>

    {#if editing}
      <div class="modal-backdrop" role="presentation" onclick={() => (editing = null)}>
        <div class="modal" role="dialog" aria-modal="true" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={(e) => { if (e.key === 'Escape') editing = null; }}>
          <form class="modal-form" onsubmit={(e) => { e.preventDefault(); saveEditing(); }}>
            <label class="field">
              <span class="form-label">{$t('organizer.item_title')}</span>
              <input class="form-input" bind:value={editing.title} required />
            </label>
            <div class="field">
              <span class="form-label">{$t('organizer.place')}</span>
              <PlaceInput
                kind="poi"
                value={editing.place_name ?? ''}
                lat={editing.lat}
                lon={editing.lon}
                placeholder={$t('organizer.place_placeholder')}
                onchange={(p) => { if (editing) { editing.place_name = p.name; editing.lat = p.lat; editing.lon = p.lon; } }}
              />
            </div>
            <div class="row">
              <label class="field">
                <span class="form-label">{$t('organizer.day')}</span>
                <select class="form-input" bind:value={editing.date}>
                  <option value={null}>{$t('organizer.no_day')}</option>
                  {#each days as d (d)}
                    <option value={d}>{fmt(d, { weekday: 'short', day: 'numeric', month: 'short' })}</option>
                  {/each}
                </select>
              </label>
              <label class="field">
                <span class="form-label">{$t('organizer.time')}</span>
                <input class="form-input" type="time" bind:value={editing.time} />
              </label>
              <label class="field">
                <span class="form-label">{$t('organizer.status')}</span>
                <select class="form-input" bind:value={editing.status}>
                  {#each STATUSES as s (s)}
                    <option value={s}>{$t(`organizer.status_${s}`)}</option>
                  {/each}
                </select>
              </label>
            </div>
            <label class="field">
              <span class="form-label">{$t('organizer.notes')}</span>
              <textarea class="form-input" rows="3" bind:value={editing.notes}></textarea>
            </label>
            <div class="form-actions">
              <button class="btn btn-primary btn-sm" type="submit">{$t('organizer.save')}</button>
              <button class="btn btn-danger btn-sm" type="button" onclick={() => editing && deleteItem(editing)}>{$t('organizer.remove')}</button>
            </div>
          </form>
        </div>
      </div>
    {/if}
  {/if}
</div>

{#snippet planItem(item: PlanItem, date: string | null)}
  {@const n = mapNumber(item, date)}
  <div
    class="item status-{item.status}"
    class:dragging={dragId === item.id}
    draggable="true"
    role="listitem"
    ondragstart={(e) => { dragId = item.id; e.dataTransfer?.setData('text/plain', item.id); }}
    ondragend={() => { dragId = null; dropTarget = null; }}
    ondragover={(e) => { if (dragId) e.preventDefault(); }}
    ondrop={(e) => { e.preventDefault(); e.stopPropagation(); dropOn(date, item.id); }}
  >
    <button class="status-dot" title={$t(`organizer.status_${item.status}`)} aria-label={$t(`organizer.status_${item.status}`)} onclick={() => cycleStatus(item)}></button>
    <button class="item-body" onclick={() => (editing = { ...item })}>
      <span class="item-line">
        {#if item.time}<span class="item-time">{item.time}</span>{/if}
        <span class="item-title">{item.title}</span>
      </span>
      {#if item.place_name || item.notes}
        <span class="item-sub">
          {#if item.place_name}<span>📍 {#if n}<b>{n}</b> · {/if}{item.place_name}</span>{/if}
          {#if item.notes}<span class="item-notes">{item.notes}</span>{/if}
        </span>
      {/if}
    </button>
    <span class="status-tag">{$t(`organizer.status_${item.status}`)}</span>
  </div>
{/snippet}

<style>
  .planner-page {
    padding: var(--space-md) var(--space-lg) var(--space-xl);
  }
  .plan-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: var(--space-md);
    flex-wrap: wrap;
    margin-bottom: var(--space-md);
  }
  .plan-header h1 {
    margin: 4px 0 0;
    font-family: var(--font-display);
    font-size: 1.6rem;
  }
  .back {
    color: var(--text-muted);
    text-decoration: none;
    font-size: 0.85rem;
  }
  .stats {
    display: flex;
    gap: var(--space-md);
    font-size: 0.85rem;
    color: var(--text-secondary);
    flex-wrap: wrap;
  }
  .stats strong {
    color: var(--text-primary);
    font-size: 1.05rem;
  }
  .stats .warn strong,
  .warn-text,
  .warn-ic {
    color: var(--warning-text, var(--warning));
  }
  .muted {
    color: var(--text-muted);
  }
  .mono {
    font-family: var(--font-mono);
    color: var(--text-secondary);
  }
  .route {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-md);
    margin-bottom: var(--space-md);
  }
  .route-chips {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    flex-wrap: wrap;
  }
  .route-arrow {
    color: var(--text-muted);
  }
  .stop-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 5px 12px 5px 5px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--stop) 45%, transparent);
    background: color-mix(in srgb, var(--stop) 12%, var(--bg-card));
    color: var(--text-primary);
    cursor: pointer;
    font: inherit;
  }
  .stop-num {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: var(--stop);
    color: #fff;
    font-size: 0.75rem;
    font-weight: 700;
    display: grid;
    place-items: center;
  }
  .stop-name {
    font-weight: 600;
  }
  .stop-dates {
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .stop-form {
    display: flex;
    gap: var(--space-sm);
    align-items: flex-end;
    flex-wrap: wrap;
    margin-top: var(--space-md);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .field.grow {
    flex: 1 1 240px;
  }
  .form-actions {
    display: flex;
    gap: var(--space-xs);
  }
  .workspace {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(360px, 1fr);
    gap: var(--space-md);
    align-items: start;
  }
  .main-col {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
    min-width: 0;
  }
  .empty {
    padding: var(--space-lg);
  }

  /* Calendar */
  .calendar {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 6px;
  }
  .cal-weekday {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    padding: 0 4px;
  }
  .day {
    all: unset;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-height: 82px;
    padding: 6px 8px;
    border-radius: var(--radius-md);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-top: 4px solid var(--stop);
    cursor: pointer;
    min-width: 0;
  }
  .day:hover {
    box-shadow: var(--shadow-card);
  }
  .day.weekend {
    background: var(--bg-subtle, var(--bg-card));
  }
  .day.selected {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .day-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 4px;
  }
  .day-date {
    font-weight: 700;
    font-size: 0.85rem;
  }
  .day-n {
    font-size: 0.65rem;
    color: var(--text-muted);
  }
  .day-city {
    font-size: 0.75rem;
    font-weight: 600;
    color: color-mix(in srgb, var(--stop) 70%, var(--text-primary));
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .day-icons {
    display: flex;
    gap: 4px;
    align-items: center;
    font-size: 0.8rem;
    margin-top: auto;
  }
  .day-count {
    margin-left: auto;
    font-size: 0.7rem;
    font-weight: 700;
    background: var(--accent);
    color: var(--accent-on, #fff);
    border-radius: 999px;
    padding: 0 6px;
  }
  .cal-blank {
    min-height: 82px;
  }
  .drop {
    outline: 2px dashed var(--accent) !important;
    outline-offset: -2px;
  }

  /* Day panel */
  .day-panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }
  .day-panel-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-md);
    border-left: 6px solid var(--stop);
    background: color-mix(in srgb, var(--stop) 8%, var(--bg-card));
  }
  .day-panel-head h2 {
    margin: 2px 0 0;
    font-size: 1.15rem;
  }
  .dp-weekday {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .dp-nav {
    display: flex;
    gap: 4px;
  }
  .facts {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--border-light, var(--border));
    font-size: 0.85rem;
  }
  .fact {
    display: flex;
    gap: 8px;
  }
  .day-items {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--space-md);
    min-height: 80px;
  }
  .note {
    display: block;
    width: calc(100% - 2 * var(--space-md));
    margin: 0 var(--space-md) var(--space-md);
    box-sizing: border-box;
    resize: vertical;
    font: inherit;
    font-size: 0.85rem;
    padding: 8px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-primary);
  }

  .item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 10px;
    border-radius: var(--radius-md);
    background: var(--bg-subtle, var(--surface-alt));
    border: 1px solid var(--border-light, var(--border));
    cursor: grab;
  }
  .item.dragging {
    opacity: 0.4;
  }
  .status-dot {
    flex: none;
    width: 14px;
    height: 14px;
    margin-top: 2px;
    border-radius: 50%;
    border: 2px solid var(--text-muted);
    background: transparent;
    padding: 0;
    cursor: pointer;
  }
  .status-todo .status-dot {
    border-color: var(--warning);
  }
  .status-booked .status-dot {
    border-color: var(--success);
    background: var(--success);
  }
  .status-done .status-dot {
    border-color: var(--text-muted);
    background: var(--text-muted);
  }
  .status-done .item-title {
    text-decoration: line-through;
    color: var(--text-muted);
  }
  .item-body {
    all: unset;
    flex: 1;
    min-width: 0;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .item-line {
    font-size: 0.88rem;
    overflow-wrap: anywhere;
  }
  .item-time {
    font-family: var(--font-mono);
    color: var(--text-secondary);
    margin-right: 6px;
  }
  .item-sub {
    display: flex;
    flex-direction: column;
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .item-notes {
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .status-tag {
    flex: none;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    margin-top: 3px;
  }
  .status-booked .status-tag {
    color: var(--success-text, var(--success));
  }
  .status-todo .status-tag {
    color: var(--warning-text, var(--warning));
  }
  .item-draft {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: 0.85rem;
    padding: 8px 10px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-primary);
  }
  .item-draft:focus,
  .note:focus {
    outline: none;
    border-style: solid;
    border-color: var(--accent);
  }

  /* Side */
  .side {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
    position: sticky;
    top: var(--space-md);
  }
  .map-overview {
    position: absolute;
    top: 10px;
    right: 10px;
    z-index: 500;
    box-shadow: var(--shadow-card);
  }
  .map-box {
    position: relative;
    height: 52vh;
    min-height: 340px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  .panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }
  .tabs {
    display: flex;
    border-bottom: 1px solid var(--border);
  }
  .tabs button {
    all: unset;
    flex: 1;
    text-align: center;
    padding: 10px;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
  }
  .tabs button.active {
    color: var(--text-primary);
    border-bottom-color: var(--accent);
  }
  .badge {
    font-size: 0.7rem;
    background: var(--bg-subtle, var(--surface-alt));
    border-radius: 999px;
    padding: 0 6px;
    margin-left: 4px;
  }
  .tab-body {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--space-md);
    max-height: 32vh;
    overflow-y: auto;
  }
  .hint {
    margin: 0 0 4px;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .task {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
  }
  .task-text {
    flex: 1;
    min-width: 0;
  }
  .task.done .task-text {
    text-decoration: line-through;
    color: var(--text-muted);
  }
  .assignee {
    font: inherit;
    font-size: 0.75rem;
    max-width: 90px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg-input, transparent);
    color: var(--text-primary);
  }
  .icon-btn {
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 1rem;
  }
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.4);
    display: grid;
    place-items: center;
    z-index: 1000;
  }
  .modal {
    background: var(--bg-card);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    width: min(520px, calc(100vw - 32px));
    box-shadow: var(--shadow-elevated);
  }
  .modal-form {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }
  .row {
    display: flex;
    gap: var(--space-sm);
  }
  .row .field {
    flex: 1;
    min-width: 0;
  }
  @media (max-width: 1000px) {
    .planner-page {
      padding: var(--space-md);
    }
    .workspace {
      grid-template-columns: 1fr;
    }
    .side {
      position: static;
    }
  }
</style>
