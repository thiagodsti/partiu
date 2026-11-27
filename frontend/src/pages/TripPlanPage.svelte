<script lang="ts">
  /* The trip organizer: a desktop-first board, one column per day, laid out the
   * way a planning spreadsheet is (city, transport, stay, things to do, notes),
   * with the route of cities above it and the ideas / to-do lists beside it.
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
    guestsApi,
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
  import { tick } from 'svelte';
  import PlaceInput from '../components/PlaceInput.svelte';
  import TripStays from '../components/TripStays.svelte';
  import TripTransport from '../components/TripTransport.svelte';
  import PlanMap, { type MapCity, type MapLine, type MapPoint } from '../components/PlanMap.svelte';
  import { formatTime, localDateKey } from '../lib/utils';
  import { toasts } from '../lib/toastStore';
  import { parseDayNote, serializeDayNote, type LegacyChecklistItem } from '../lib/dayNotes';
  import { stopColor as sharedStopColor } from '../lib/planColors';

  interface Props {
    params: { id: string };
  }
  const { params }: Props = $props();

  /** Every write still in flight — notes and planner rows alike — so "Save
   * and back" leaves only once they have all landed. */
  const pendingSaves = new Set<Promise<unknown>>();
  /** Set by any write that failed and not since repaired; "Save and back"
   * will not leave the page while it is set, and the header says so. */
  let writeFailed = $state(false);
  /** `sticky`: a failure marks the page as not fully saved until a reload.
   * Note saves pass false — they are retried from `unsavedNotes` instead. */
  function track<T>(p: Promise<T>, sticky = true): Promise<T> {
    pendingSaves.add(p);
    p.catch(() => {
      if (sticky) writeFailed = true;
    }).finally(() => pendingSaves.delete(p));
    return p;
  }
  /** plannerApi with every call tracked. */
  const api = Object.fromEntries(
    Object.entries(plannerApi).map(([k, fn]) => [
      k,
      (...args: unknown[]) => track((fn as (...a: unknown[]) => Promise<unknown>)(...args)),
    ]),
  ) as unknown as typeof plannerApi;

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

  async function load() {
    loading = true;
    error = null;
    try {
      const [tr, segs, sts, plan, dn, ppl] = await Promise.all([
        tripsApi.get(params.id),
        segmentsApi.list(params.id).catch(() => [] as TripSegment[]),
        staysApi.list(params.id).catch(() => [] as TripStay[]),
        plannerApi.get(params.id),
        dayNotesApi.list(params.id).catch(() => null),
        expensesApi.participants(params.id).catch(() => [] as Participant[]),
      ]);
      trip = tr;
      segments = segs;
      stays = sts;
      stops = plan.stops;
      items = plan.items;
      tasks = plan.tasks;
      people = ppl;
      // An unreadable note list must not look empty: saving into it would
      // overwrite what is stored. The notes stay read-only until a reload.
      notesUnavailable = dn === null;
      const parsed = (dn ?? []).map((n) => [n.date, parseDayNote(n.content)] as const);
      notes = Object.fromEntries(parsed.map(([d, c]) => [d, c.note]));
      savedNotes = { ...notes };
      legacyItems = Object.fromEntries(parsed.map(([d, c]) => [d, c.items]));
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
    const dt = new Date(Date.UTC(y, m - 1, d + n));
    return dt.toISOString().slice(0, 10);
  }

  /** Every day from the trip's first to its last, widened by the route so a
   * trip planned before any flight still gets a board. */
  const days = $derived.by<string[]>(() => {
    const bounds = [
      trip?.start_date ?? trip?.planned_start_date,
      trip?.end_date ?? trip?.planned_end_date,
      ...stops.flatMap((s) => [s.start_date, s.end_date]),
      // A dated item keeps its day on the board even after the route that
      // reached it shrinks, rather than vanishing from every list.
      ...items.map((i) => i.date),
    ].filter((d): d is string => !!d);
    if (bounds.length === 0) return [];
    bounds.sort();
    const out: string[] = [];
    for (let d = bounds[0]; d <= bounds[bounds.length - 1] && out.length < 400; d = addDays(d, 1)) {
      out.push(d);
    }
    return out;
  });

  const stopColor = (s: PlanStop) => sharedStopColor(stops, s);

  function stopsOn(date: string): PlanStop[] {
    return stops.filter((s) => s.start_date <= date && date <= s.end_date);
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
    flight?: Flight;
    segment?: TripSegment;
  }

  function movesOn(date: string): Move[] {
    const out: (Move & { sort: string })[] = [];
    for (const f of flights) {
      if (localDateKey(f.departure_datetime, f.departure_timezone) !== date) continue;
      out.push({
        key: `f-${f.id}`,
        icon: '✈️',
        label: `${f.flight_number} ${f.departure_airport}→${f.arrival_airport}`,
        time: formatTime(f.departure_datetime, f.departure_timezone),
        sort: f.departure_datetime ?? '',
        flight: f,
      });
    }
    for (const s of segments) {
      if (localDateKey(s.departure_datetime, s.departure.timezone) !== date) continue;
      const icon = { train: '🚆', bus: '🚌', ferry: '⛴️', car: '🚗' }[s.type] ?? '→';
      out.push({
        key: `s-${s.id}`,
        icon,
        label: `${s.departure.name} → ${s.arrival.name}`,
        time: formatTime(s.departure_datetime, s.departure.timezone),
        sort: s.departure_datetime,
        segment: s,
      });
    }
    return out.sort((a, b) => a.sort.localeCompare(b.sort));
  }

  /** The stay for the night that starts on `date`. */
  function stayFor(date: string): TripStay | undefined {
    return stays.find((s) => s.check_in_date <= date && date < s.check_out_date);
  }

  /** A night of the trip with no booking. The last day has no night, and a
   * day spent in the air (a flight leaving that evening) is not one either. */
  function missingStay(date: string): boolean {
    if (date === days[days.length - 1] || stayFor(date)) return false;
    return !flights.some(
      (f) =>
        localDateKey(f.departure_datetime, f.departure_timezone) === date &&
        localDateKey(f.arrival_datetime, f.arrival_timezone) !== date,
    );
  }

  const missingNights = $derived(days.filter(missingStay).length);

  function weekday(date: string): string {
    const w = new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' });
    return w.charAt(0).toUpperCase() + w.slice(1);
  }
  function dayMonth(date: string): string {
    return new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

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
      if (stopForm.id) await api.updateStop(params.id, stopForm.id, data);
      else await api.createStop(params.id, data);
      stopForm = null;
      stops = (await plannerApi.get(params.id)).stops;
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function deleteStop() {
    if (!stopForm?.id) return;
    await api.deleteStop(params.id, stopForm.id);
    stops = stops.filter((s) => s.id !== stopForm?.id);
    stopForm = null;
  }

  // ---- Items ----------------------------------------------------------------

  const STATUSES: PlanItemStatus[] = ['idea', 'todo', 'booked', 'done'];

  function itemsOn(date: string | null): PlanItem[] {
    return items
      .filter((i) => i.date === date)
      .sort((a, b) => a.sort_order - b.sort_order || (a.time ?? '').localeCompare(b.time ?? ''));
  }

  let drafts = $state<Record<string, string>>({});
  const IDEAS = '__ideas__';

  /** "07:20 Muralha" sets the time; everything else is the title. */
  function parseDraft(raw: string): { title: string; time: string | null } {
    const m = raw.trim().match(/^(\d{1,2})[:h](\d{2})\s+(.+)$/);
    if (m && Number(m[1]) < 24 && Number(m[2]) < 60) {
      return { time: `${m[1].padStart(2, '0')}:${m[2]}`, title: m[3] };
    }
    return { time: null, title: raw.trim() };
  }

  async function addItem(date: string | null) {
    const key = date ?? IDEAS;
    const raw = drafts[key] ?? '';
    if (!raw.trim()) return;
    const { title, time } = parseDraft(raw);
    drafts[key] = '';
    try {
      const { id } = await api.createItem(params.id, { title, time, date, status: date ? 'todo' : 'idea' });
      const order = itemsOn(date).length;
      items = [
        ...items,
        { id, title, time, date, notes: null, place_name: null, lat: null, lon: null, status: date ? 'todo' : 'idea', sort_order: order },
      ];
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function cycleStatus(item: PlanItem) {
    const prev = item.status;
    const next = STATUSES[(STATUSES.indexOf(prev) + 1) % STATUSES.length];
    item.status = next;
    try {
      await api.updateItem(params.id, item.id, { status: next });
    } catch (err) {
      item.status = prev;
      toasts.show((err as Error).message, 'error');
    }
  }

  let editing = $state<PlanItem | null>(null);

  async function saveEditing() {
    if (!editing) return;
    const e = {
      ...editing,
      title: editing.title.trim(),
      time: editing.time || null,
      place_name: editing.place_name || null,
    };
    if (!e.title) {
      toasts.show($t('organizer.title_required'), 'error');
      return;
    }
    try {
      await api.updateItem(params.id, e.id, {
        title: e.title,
        time: e.time,
        notes: e.notes,
        status: e.status,
        date: e.date,
        place_name: e.place_name,
        lat: e.place_name ? e.lat : null,
        lon: e.place_name ? e.lon : null,
      });
      // Only now: a rejected save keeps the dialog and the draft open.
      const idx = items.findIndex((i) => i.id === e.id);
      if (idx >= 0) items[idx] = e;
      editing = null;
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function deleteItem(item: PlanItem) {
    items = items.filter((i) => i.id !== item.id);
    editing = null;
    await api.deleteItem(params.id, item.id);
  }

  // Drag and drop: an item moves to a day (or back to the ideas) at a position.
  let dragId = $state<string | null>(null);
  let dropTarget = $state<string | null>(null);

  // HTML drag and drop is a mouse feature: a phone never fires `dragstart` on
  // a touch, so on a touch screen an item is picked up by pressing and holding
  // it, then carried under the finger. Where it lands is read off the element
  // under the finger (`data-drop-date` / `data-item-id`), the same targets the
  // mouse handlers use. The native path is switched off there (`draggable`),
  // so the two cannot both fire on one gesture.
  const LONG_PRESS_MS = 350;
  /** A finger travelling this far before the press completes is a scroll. */
  const PRESS_SLOP_PX = 10;
  const touchOnly = typeof window !== 'undefined' && window.matchMedia('(hover: none)').matches;
  let touchGhost = $state<{ title: string; x: number; y: number } | null>(null);

  function dropAt(x: number, y: number): { key: string; date: string | null; beforeId: string | null } | null {
    const el = document.elementFromPoint(x, y);
    const zone = el?.closest<HTMLElement>('[data-drop-date]');
    if (!el || !zone) return null;
    const date = zone.dataset.dropDate || null;
    const before = el.closest<HTMLElement>('[data-item-id]');
    return { key: zone.dataset.dropKey ?? date ?? IDEAS, date, beforeId: before?.dataset.itemId ?? null };
  }

  /** The tap a lifted finger produces after a drop must not open the editor.
   * Caught on the window, not on the item: the drop re-renders the item in
   * its new list, often right under the finger, so the click lands on a node
   * the dragged one never knew about. */
  let swallowClickUntil = 0;
  $effect(() => {
    const swallow = (e: MouseEvent) => {
      if (Date.now() > swallowClickUntil) return;
      swallowClickUntil = 0;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener('click', swallow, true);
    return () => window.removeEventListener('click', swallow, true);
  });

  function touchDraggable(item: PlanItem) {
    return (node: HTMLElement) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      let raf = 0;
      let active = false;
      let x = 0;
      let y = 0;
      let x0 = 0;
      let y0 = 0;
      const cancelPress = () => {
        clearTimeout(timer);
        timer = undefined;
      };

      // Near the top or bottom edge the page scrolls, so a day far from the
      // ideas list can still be reached in one gesture.
      const edgeScroll = () => {
        if (!active) return;
        const edge = 72;
        if (y < edge) window.scrollBy(0, -14);
        else if (y > window.innerHeight - edge) window.scrollBy(0, 14);
        dropTarget = dropAt(x, y)?.key ?? null;
        raf = requestAnimationFrame(edgeScroll);
      };
      const start = (e: TouchEvent) => {
        if (e.touches.length !== 1) return;
        // The status dot is its own control.
        if ((e.target as HTMLElement).closest('.status-dot')) return;
        x = e.touches[0].clientX;
        y = e.touches[0].clientY;
        x0 = x;
        y0 = y;
        cancelPress();
        timer = setTimeout(() => {
          timer = undefined;
          active = true;
          dragId = item.id;
          touchGhost = { title: item.title, x, y };
          navigator.vibrate?.(15);
          raf = requestAnimationFrame(edgeScroll);
        }, LONG_PRESS_MS);
      };
      const move = (e: TouchEvent) => {
        x = e.touches[0].clientX;
        y = e.touches[0].clientY;
        if (!active) {
          // Once past the slop it is a scroll, even if the finger comes back.
          if (timer && Math.hypot(x - x0, y - y0) > PRESS_SLOP_PX) cancelPress();
          return;
        }
        e.preventDefault(); // carrying the item, not scrolling the page
        touchGhost = { title: item.title, x, y };
      };
      const end = (e: TouchEvent) => {
        cancelPress();
        if (!active) return;
        active = false;
        cancelAnimationFrame(raf);
        touchGhost = null;
        if (e.cancelable) e.preventDefault(); // no tap — the editor stays shut
        swallowClickUntil = Date.now() + 400;
        const at = e.type === 'touchend' ? dropAt(x, y) : null;
        // Lifted over itself: put back where it was, not appended to the end.
        if (at && at.beforeId !== item.id) dropOn(at.date, at.beforeId);
        else {
          dragId = null;
          dropTarget = null;
        }
      };
      // Holding a finger on text opens the selection / context menu otherwise.
      const menu = (e: Event) => {
        if (active || timer) e.preventDefault();
      };
      node.addEventListener('touchstart', start, { passive: true });
      node.addEventListener('touchmove', move, { passive: false });
      node.addEventListener('touchend', end);
      node.addEventListener('touchcancel', end);
      node.addEventListener('contextmenu', menu);
      return () => {
        cancelPress();
        cancelAnimationFrame(raf);
        // Removed mid-drag (a reload after a failed drop): leave no ghost.
        if (active) {
          active = false;
          touchGhost = null;
          if (dragId === item.id) {
            dragId = null;
            dropTarget = null;
          }
        }
        node.removeEventListener('touchstart', start);
        node.removeEventListener('touchmove', move);
        node.removeEventListener('touchend', end);
        node.removeEventListener('touchcancel', end);
        node.removeEventListener('contextmenu', menu);
      };
    };
  }

  /** Pulls an unscheduled idea or place onto a day, without a drag — and
   * without scrolling down to the ideas list, which on a phone sits below
   * every day. */
  function scheduleIdea(id: string, date: string) {
    if (!id) return;
    dragId = id;
    dropOn(date, null);
  }

  async function dropOn(date: string | null, beforeId: string | null) {
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
      changes.push(api.updateItem(params.id, it.id, patch));
    });
    items = [...items];
    try {
      await Promise.all(changes);
    } catch (err) {
      toasts.show((err as Error).message, 'error');
      load();
    }
  }

  // ---- Day notes --------------------------------------------------------------

  // On a phone the board's columns do not fit, so the days are listed one
  // under the other instead; same data, same editors.
  const NARROW = '(max-width: 760px)';
  let narrow = $state(typeof window !== 'undefined' && window.matchMedia(NARROW).matches);
  $effect(() => {
    const mq = window.matchMedia(NARROW);
    const on = () => (narrow = mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  });


  /** What the server last confirmed per day, apart from the text on screen:
   * a failed save must stay different from it so the next blur retries. */
  let savedNotes = $state<Record<string, string>>({});
  let notesUnavailable = $state(false);
  /** Days whose text on screen differs from what the server confirmed. */
  const unsavedNotes = $derived(Object.keys(notes).filter((d) => (notes[d] ?? '') !== (savedNotes[d] ?? '')));
  /** A legacy checklist still inside a day's note (see lib/dayNotes). */
  let legacyItems: Record<string, LegacyChecklistItem[]> = {};
  /** One save at a time per day, in order, so an older text can never land
   * after a newer one. */
  const noteChains: Record<string, Promise<unknown>> = {};

  function saveNote(date: string, content: string): Promise<unknown> {
    if (notesUnavailable) return Promise.resolve();
    notes[date] = content;
    const run = async () => {
      if ((savedNotes[date] ?? '') === content) return;
      try {
        await dayNotesApi.upsert(params.id, date, serializeDayNote(content, legacyItems[date]));
        savedNotes = { ...savedNotes, [date]: content };
      } catch (err) {
        toasts.show(`${$t('organizer.note_not_saved')} (${(err as Error).message})`, 'error');
        throw err;
      }
    };
    const next = (noteChains[date] ?? Promise.resolve()).catch(() => {}).then(run);
    noteChains[date] = next;
    return track(next, false);
  }

  // ---- Dialog focus -----------------------------------------------------------
  //
  // Opening a dialog moves focus to its first field, and closing it returns
  // focus to whatever opened it, so the keyboard never keeps working the board
  // behind an open dialog.

  let returnFocus: HTMLElement | null = null;
  function dialogFocus(node: HTMLElement) {
    returnFocus = document.activeElement as HTMLElement | null;
    queueMicrotask(() => {
      const first = node.querySelector<HTMLElement>('input, select, textarea, button:not(.modal-close)');
      first?.focus();
    });
    return {
      destroy() {
        returnFocus?.focus?.();
        returnFocus = null;
      },
    };
  }

  // The booking dialog stays mounted (its editors keep their state), so it
  // takes focus when a form opens and gives it back when the form closes.
  let bookingReturn: HTMLElement | null = null;
  $effect(() => {
    const open = stayFormOpen || legFormOpen;
    if (open && !bookingReturn) {
      bookingReturn = (document.activeElement as HTMLElement | null) ?? document.body;
      tick().then(() =>
        document
          .querySelector<HTMLElement>('.booking-modal input, .booking-modal select, .booking-modal textarea')
          ?.focus(),
      );
    } else if (!open && bookingReturn) {
      bookingReturn.focus?.();
      bookingReturn = null;
    }
  });

  /** Keeps Tab inside an open dialog. */
  function trapTab(e: KeyboardEvent) {
    if (e.key !== 'Tab') return;
    const box = e.currentTarget as HTMLElement;
    const focusable = [...box.querySelectorAll<HTMLElement>('input, select, textarea, button, a[href]')].filter(
      (el) => !el.hasAttribute('disabled') && el.offsetParent !== null,
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // ---- Bookings: the trip page's own editors, in a dialog ---------------------
  //
  // Stays and ground legs are edited with the same forms as on the trip page
  // (TripStays / TripTransport in editor-only mode), so there is one editor
  // per thing. Flights keep their own edit page, which is far richer.

  let staysEditor: ReturnType<typeof TripStays> | undefined = $state();
  let legsEditor: ReturnType<typeof TripTransport> | undefined = $state();
  let stayFormOpen = $state(false);
  let legFormOpen = $state(false);

  /** A new stay for the night of `date`, running to the end of that city's
   * stop when there is one. */
  function closeBookingEditors() {
    staysEditor?.closeForm();
    legsEditor?.closeForm();
  }

  function addStay(date: string) {
    const stop = stops.find((s) => s.start_date <= date && date < s.end_date);
    staysEditor?.openAdd(date, stop?.end_date ?? addDays(date, 1));
  }

  /** Everything saves as it is changed; this waits for anything still in
   * flight (a note being typed) and goes back to the trip. */
  async function saveAndBack() {
    (document.activeElement as HTMLElement | null)?.blur();
    await tick();
    // A note whose save failed earlier gets another try now.
    for (const date of unsavedNotes) saveNote(date, notes[date] ?? '');
    // Wait until nothing is in flight, including writes started meanwhile.
    while (pendingSaves.size) await Promise.allSettled([...pendingSaves]);
    if (writeFailed) {
      // A failed item write is not replayed; a reload shows what was kept.
      toasts.show($t('organizer.reload_to_check'), 'error');
      return;
    }
    if (unsavedNotes.length) {
      toasts.show($t('organizer.not_all_saved'), 'error');
      return;
    }
    window.location.hash = `#/trips/${params.id}`;
  }

  // ---- Tasks ------------------------------------------------------------------

  let taskDraft = $state('');

  function personKey(type: string | null, id: number | null): string {
    return type && id != null ? `${type}:${id}` : '';
  }

  async function addTask() {
    const text = taskDraft.trim();
    if (!text) return;
    taskDraft = '';
    const { id } = await api.createTask(params.id, { text });
    tasks = [...tasks, { id, text, done: false, assignee_type: null, assignee_id: null, sort_order: tasks.length }];
  }

  async function toggleTask(task: PlanTask) {
    task.done = !task.done;
    await api.updateTask(params.id, task.id, { done: task.done });
  }

  async function assign(task: PlanTask, key: string) {
    const [type, id] = key ? key.split(':') : [null, null];
    task.assignee_type = (type as 'user' | 'guest' | null) ?? null;
    task.assignee_id = id ? Number(id) : null;
    try {
      await api.updateTask(params.id, task.id, {
        assignee_type: task.assignee_type,
        assignee_id: task.assignee_id,
      });
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  async function deleteTask(task: PlanTask) {
    tasks = tasks.filter((x) => x.id !== task.id);
    await api.deleteTask(params.id, task.id);
  }

  const openTasks = $derived(tasks.filter((x) => !x.done).length);

  // The side lists can be hidden so the board and the map get the full width.
  // Remembered per browser: a viewing preference, not trip data.
  const SIDE_KEY = 'partiu.organizer.sideHidden';
  let sideHidden = $state(
    (() => {
      try {
        return localStorage.getItem(SIDE_KEY) === '1';
      } catch {
        return false;
      }
    })(),
  );
  function toggleSide() {
    sideHidden = !sideHidden;
    try {
      localStorage.setItem(SIDE_KEY, sideHidden ? '1' : '0');
    } catch {
      /* private mode: the toggle still works for this visit */
    }
  }

  // ---- Places to visit ----------------------------------------------------------
  //
  // An unscheduled item with a place is a "place to visit"; one without is an
  // idea. Same rows, two lists: the places one adds through the sights search,
  // so each arrives with coordinates and is on the map at once.

  const PLACES = '__places__';
  const ideas = $derived(itemsOn(null).filter((i) => i.lat == null));
  const places = $derived(itemsOn(null).filter((i) => i.lat != null));

  /** The middle of the route, to rank sights near this trip first. */
  const routeCenter = $derived.by<{ lat: number; lon: number } | null>(() => {
    const pts = [
      ...stops.map((s) => [s.lat, s.lon]),
      ...stays.map((s) => [s.place.lat, s.place.lon]),
    ].filter((p): p is [number, number] => p[0] != null && p[1] != null);
    if (!pts.length) return null;
    return {
      lat: pts.reduce((a, p) => a + p[0], 0) / pts.length,
      lon: pts.reduce((a, p) => a + p[1], 0) / pts.length,
    };
  });

  /** Remounts the search box after a pick, which clears it. */
  let placeSearchKey = $state(0);

  async function addPlace(p: PickedPlace) {
    if (p.lat == null || p.lon == null) return;
    placeSearchKey++;
    const data = { title: p.name, place_name: p.name, lat: p.lat, lon: p.lon, date: null, status: 'idea' as const };
    try {
      const { id } = await api.createItem(params.id, data);
      items = [...items, { id, ...data, time: null, notes: null, sort_order: itemsOn(null).length }];
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  // ---- People ---------------------------------------------------------------------

  const NEW_PERSON = '__new__';
  let newPersonFor = $state<string | null>(null);
  let newPersonName = $state('');

  /** Add a companion to the trip as a guest (the same people expenses can
   * split with), then assign the task to them. */
  async function addPerson(task: PlanTask) {
    const name = newPersonName.trim();
    newPersonFor = null;
    newPersonName = '';
    if (!name) return;
    try {
      const guest = await guestsApi.create(name);
      await guestsApi.addToTrip(params.id, guest.id);
      people = await expensesApi.participants(params.id);
      await assign(task, personKey('guest', guest.id));
    } catch (err) {
      toasts.show((err as Error).message, 'error');
    }
  }

  // ---- Map --------------------------------------------------------------------
  //
  // Everything in the plan that has a place: the route's cities in order, the
  // stays, the ground legs and the plan items. Clicking a day's header
  // highlights that day here and flies to it; clicking it again shows it all.

  let focusDay = $state<string | null>(null);

  function toggleFocus(date: string) {
    focusDay = focusDay === date ? null : date;
    // On a phone the map is far below the day; bring it into view.
    if (narrow && focusDay) {
      document.querySelector('.map-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  /** Where you sleep on `date`, else where the day starts. */
  function cityOf(date: string): PlanStop | undefined {
    return (
      stops.find((s) => s.start_date <= date && date < s.end_date) ??
      stops.find((s) => s.start_date <= date && date <= s.end_date)
    );
  }

  /** A frame in the city's colour around each run of days in that city, so
   * "all of this is Beijing" reads at a glance. A day belongs to the city you
   * sleep in, so a travel day opens the next city's frame. Drawn with inset
   * shadows, which need no layout space and sit inside the sticky header. */
  function frame(date: string, pos: 'top' | 'mid' | 'bottom'): string {
    const c = cityOf(date);
    if (!c) return '';
    const i = days.indexOf(date);
    const col = stopColor(c);
    const sh: string[] = [];
    if (i === 0 || cityOf(days[i - 1]) !== c) sh.push(`inset 3px 0 0 ${col}`);
    if (i === days.length - 1 || cityOf(days[i + 1]) !== c) sh.push(`inset -3px 0 0 ${col}`);
    if (pos === 'top') sh.push(`inset 0 3px 0 ${col}`);
    if (pos === 'bottom') sh.push(`inset 0 -3px 0 ${col}`);
    sh.push('inset 0 0 0 transparent');
    return `--frame:${col};--frame-shadow:${sh.join(',')}`;
  }

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
    const sel = focusDay;
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
    for (const date of [...days, null]) {
      itemsOn(date).forEach((it, i) => {
        if (it.lat == null || it.lon == null) return;
        const city = date ? cityOf(date) : undefined;
        out.push({
          id: it.id,
          kind: 'item',
          title: `${date ? `${dayMonth(date)} · ` : ''}${it.time ? `${it.time} ` : ''}${it.title}`,
          lat: it.lat,
          lon: it.lon,
          active: date === sel,
          color: city ? stopColor(city) : '#64748b',
          label: date === sel ? String(i + 1) : '',
        });
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

  const mapFocus = $derived.by<[number, number][]>(() => {
    if (!focusDay) return [];
    const active = mapPoints.filter((p) => p.active).map((p) => [p.lat, p.lon] as [number, number]);
    if (active.length) return active;
    const city = cityOf(focusDay);
    return city && city.lat != null && city.lon != null ? [[city.lat, city.lon]] : [];
  });

  function pointClicked(p: MapPoint) {
    const it = items.find((i) => i.id === p.id);
    if (it) editing = { ...it };
  }

  function cityClicked(name: string) {
    const s = stops.find((x) => x.name === name);
    if (s) focusDay = s.start_date;
  }

  /** The number an item carries on the map while its day is highlighted. */
  function mapNumber(item: PlanItem, date: string | null): number {
    if (!date || date !== focusDay || item.lat == null) return 0;
    return itemsOn(date).indexOf(item) + 1;
  }
</script>

<!-- Esc closes whichever dialog is open, wherever focus happens to be: the
     booking editors open from a board button, which keeps the focus. -->
<svelte:window
  onkeydown={(e) => {
    if (e.key !== 'Escape') return;
    if (editing) editing = null;
    else if (stayFormOpen || legFormOpen) closeBookingEditors();
  }}
/>

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
      <div class="save-box">
        {#if writeFailed || unsavedNotes.length}
          <span class="autosave failed">⚠ {$t('organizer.not_all_saved')}</span>
        {:else}
          <span class="autosave">✓ {$t('organizer.autosaved')}</span>
        {/if}
        <button class="btn btn-primary btn-sm" data-testid="save-and-back" onclick={saveAndBack}>{$t('organizer.save_and_back')}</button>
      </div>
      <div class="stats">
        <span><strong>{days.length}</strong> {$t('organizer.days')}</span>
        <span><strong>{stops.length}</strong> {$t('organizer.cities')}</span>
        <span class:warn={missingNights > 0}>
          <strong>{missingNights}</strong> {$t('organizer.nights_without_stay')}
        </span>
        <span><strong>{openTasks}</strong> {$t('organizer.open_tasks')}</span>
        <button
          class="btn btn-secondary btn-sm side-toggle"
          data-testid="toggle-side"
          aria-pressed={sideHidden}
          onclick={toggleSide}
        >
          {sideHidden ? `⇤ ${$t('organizer.show_lists')}` : `${$t('organizer.hide_lists')} ⇥`}
        </button>
      </div>
    </header>

    <!-- Route -->
    <section class="route" aria-label={$t('organizer.route')}>
      <h2>{$t('organizer.route')}</h2>
      <div class="route-chips">
        {#each stops as stop, i (stop.id)}
          {#if i > 0}<span class="route-arrow">→</span>{/if}
          <button class="stop-chip" style="--stop:{stopColor(stop)}" onclick={() => openStop(stop)}>
            <span class="stop-dot"></span>
            <span class="stop-name">{stop.name}</span>
            <span class="stop-dates">{dayMonth(stop.start_date)} – {dayMonth(stop.end_date)} · {$t('organizer.nights', { values: { n: nightsOf(stop) } })}</span>
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

    <div class="workspace" class:side-hidden={sideHidden && !narrow}>
      <div class="main-col">
        <!-- Board -->
        {#if days.length === 0}
          <p class="muted board-empty">{$t('organizer.no_days')}</p>
        {:else if narrow}
          <div class="day-list">
            {#each days as date, i (date)}
              {@const city = cityOf(date)}
              {@const stay = stayFor(date)}
              <article class="day-card-m" style={city ? `--frame:${stopColor(city)}` : ''}>
                <header class="dm-head">
                  <div>
                    <span class="day-num">{$t('planner.day_prefix')} {i + 1}</span>
                    <span class="dm-date">{weekday(date)} {dayMonth(date)}</span>
                  </div>
                  <div class="dm-cities">
                    {#each stopsOn(date) as s (s.id)}
                      <span class="city-tag" style="--stop:{stopColor(s)}">{s.name}</span>
                    {/each}
                  </div>
                  <button class="dm-map" class:on={focusDay === date} aria-label={$t('organizer.show_on_map')} onclick={() => toggleFocus(date)}>🗺</button>
                </header>

                <div class="dm-section">
                    {#each movesOn(date) as m (m.key)}
                      {#if m.flight}
                        <a class="move editable" href="#/trips/{params.id}/flights/{m.flight.id}/edit?from=planner">
                          <span>{m.icon}</span> <span class="move-time">{m.time}</span> {m.label}
                        </a>
                      {:else if m.segment}
                        {@const seg = m.segment}
                        <button class="move editable" onclick={() => legsEditor?.openEdit(seg)}>
                          <span>{m.icon}</span> <span class="move-time">{m.time}</span> {m.label}
                        </button>
                      {/if}
                    {/each}
                    <a class="dm-add-transport" href="#/trips/{params.id}/add-transport?from=planner">+ {$t('organizer.add_transport')}</a>
                  </div>

                {#if stay || missingStay(date)}
                  <div class="dm-section">
                    {#if stay}
                      <button class="stay editable" onclick={() => staysEditor?.openEdit(stay)}>🏨 {stay.place.name}</button>
                    {:else}
                      <button class="no-stay editable" onclick={() => addStay(date)}>⚠ {$t('organizer.no_stay')} · <u>{$t('organizer.add_stay')}</u></button>
                    {/if}
                  </div>
                {/if}

                <div
                  class="dm-section dm-items"
                  class:drop={dropTarget === date}
                  role="list"
                  data-drop-date={date}
                  ondragover={(e) => { e.preventDefault(); dropTarget = date; }}
                  ondragleave={() => { if (dropTarget === date) dropTarget = null; }}
                  ondrop={(e) => { e.preventDefault(); dropOn(date, null); }}
                >
                  {#each itemsOn(date) as item (item.id)}
                    {@render planItem(item, date)}
                  {/each}
                  <form class="draft-form" onsubmit={(e) => { e.preventDefault(); addItem(date); }}>
                    <input
                      class="item-draft"
                      placeholder={$t('organizer.add_item')}
                      bind:value={drafts[date]}
                      enterkeyhint="done"
                      onblur={() => addItem(date)}
                    />
                  </form>
                  {@render ideaPicker(date)}
                </div>

                <textarea
                  class="note dm-note"
                  rows="2"
                  placeholder={$t('organizer.notes') + '…'}
                  value={notes[date] ?? ''}
                  readonly={notesUnavailable}
                  title={notesUnavailable ? $t('organizer.notes_unavailable') : undefined}
                  onblur={(e) => saveNote(date, (e.currentTarget as HTMLTextAreaElement).value)}
                ></textarea>
              </article>
            {/each}
          </div>
        {:else}
          <div class="board" style="--cols:{days.length}">
            <div class="lane-label corner"></div>
            {#each days as date, i (date)}
              <button
                style={frame(date, 'top')}
                class="day-head"
                class:weekend={[0, 6].includes(new Date(`${date}T12:00:00`).getDay())}
                class:focused={focusDay === date}
                title={$t('organizer.show_on_map')}
                onclick={() => toggleFocus(date)}
              >
                <span class="day-num">{$t('planner.day_prefix')} {i + 1}</span>
                <span class="day-date">{weekday(date)} {dayMonth(date)}</span>
              </button>
            {/each}

            <div class="lane-label">{$t('organizer.city')}</div>
            {#each days as date (date)}
              <div class="cell city-cell" style={frame(date, 'mid')}>
                {#each stopsOn(date) as s (s.id)}
                  <span class="city-tag" style="--stop:{stopColor(s)}">{s.name}</span>
                {:else}
                  <span class="muted small">—</span>
                {/each}
              </div>
            {/each}

            <div class="lane-label">{$t('organizer.transport')}</div>
            {#each days as date (date)}
              <div class="cell" style={frame(date, 'mid')}>
                {#each movesOn(date) as m (m.key)}
                  {#if m.flight}
                    <a class="move editable" href="#/trips/{params.id}/flights/{m.flight.id}/edit?from=planner" title={$t('organizer.edit')}>
                      <span>{m.icon}</span> <span class="move-time">{m.time}</span> {m.label}
                    </a>
                  {:else if m.segment}
                    {@const seg = m.segment}
                    <button class="move editable" title={$t('organizer.edit')} onclick={() => legsEditor?.openEdit(seg)}>
                      <span>{m.icon}</span> <span class="move-time">{m.time}</span> {m.label}
                    </button>
                  {/if}
                {/each}
                <a class="cell-add" href="#/trips/{params.id}/add-transport?from=planner">+ {$t('organizer.add_transport')}</a>
              </div>
            {/each}

            <div class="lane-label">{$t('organizer.stay')}</div>
            {#each days as date (date)}
              {@const stay = stayFor(date)}
              <div class="cell" style={frame(date, 'mid')}>
                {#if stay}
                  <button class="stay editable" title={stay.place.address ?? $t('organizer.edit')} onclick={() => staysEditor?.openEdit(stay)}>🏨 {stay.place.name}</button>
                {:else if missingStay(date)}
                  <button class="no-stay editable" onclick={() => addStay(date)}>⚠ {$t('organizer.no_stay')} · <u>{$t('organizer.add_stay')}</u></button>
                {:else if date !== days[days.length - 1]}
                  <button class="cell-add" onclick={() => addStay(date)}>+ {$t('organizer.add_stay')}</button>
                {/if}
              </div>
            {/each}

            <div class="lane-label">{$t('organizer.todo_lane')}</div>
            {#each days as date (date)}
              <div
                class="cell items-cell"
                style={frame(date, 'mid')}
                class:drop={dropTarget === date}
                role="list"
                data-drop-date={date}
                ondragover={(e) => { e.preventDefault(); dropTarget = date; }}
                ondragleave={() => { if (dropTarget === date) dropTarget = null; }}
                ondrop={(e) => { e.preventDefault(); dropOn(date, null); }}
              >
                {#each itemsOn(date) as item (item.id)}
                  {@render planItem(item, date)}
                {/each}
                <form class="draft-form" onsubmit={(e) => { e.preventDefault(); addItem(date); }}>
                  <input
                    class="item-draft"
                    placeholder={$t('organizer.add_item')}
                    bind:value={drafts[date]}
                    enterkeyhint="done"
                    onblur={() => addItem(date)}
                  />
                </form>
                {@render ideaPicker(date)}
              </div>
            {/each}

            <div class="lane-label">{$t('organizer.notes')}</div>
            {#each days as date (date)}
              <div class="cell" style={frame(date, 'bottom')}>
                <textarea
                  class="note"
                  rows="3"
                  placeholder="…"
                  value={notes[date] ?? ''}
                  readonly={notesUnavailable}
                  title={notesUnavailable ? $t('organizer.notes_unavailable') : undefined}
                  onblur={(e) => saveNote(date, (e.currentTarget as HTMLTextAreaElement).value)}
                ></textarea>
              </div>
            {/each}
          </div>
        {/if}


      <section class="map-section" aria-label={$t('organizer.map')}>
        <div class="map-head">
          <h2>🗺 {$t('organizer.map')}</h2>
          <span class="hint">
            {#if focusDay}{weekday(focusDay)} {dayMonth(focusDay)}{#if cityOf(focusDay)} · {cityOf(focusDay)?.name}{/if}{:else}{$t('organizer.map_hint')}{/if}
          </span>
          {#if focusDay}
            <button class="btn btn-secondary btn-sm" onclick={() => (focusDay = null)}>{$t('organizer.whole_route')}</button>
          {/if}
        </div>
        <div class="map-box">
          <PlanMap cities={mapCities} points={mapPoints} lines={mapLines} focus={mapFocus} onCityClick={cityClicked} onPointClick={pointClicked} />
        </div>
      </section>
      </div>

      <!-- Side panels -->
      <aside class="side" hidden={sideHidden && !narrow}>
        <section
          class="panel"
          class:drop={dropTarget === PLACES}
          role="list"
          data-drop-date=""
          data-drop-key={PLACES}
          ondragover={(e) => { e.preventDefault(); dropTarget = PLACES; }}
          ondragleave={() => { if (dropTarget === PLACES) dropTarget = null; }}
          ondrop={(e) => { e.preventDefault(); dropOn(null, null); }}
        >
          <h2>📍 {$t('organizer.places')}</h2>
          <p class="hint">{$t('organizer.places_hint')}</p>
          {#each places as item (item.id)}
            {@render planItem(item, null)}
          {/each}
          {#key placeSearchKey}
            <div class="place-search" data-testid="place-search">
              <PlaceInput
                kind="poi"
                value=""
                lat={null}
                lon={null}
                near={routeCenter}
                placeholder={$t('organizer.add_place')}
                onchange={addPlace}
              />
            </div>
          {/key}
        </section>

        <section
          class="panel"
          class:drop={dropTarget === IDEAS}
          role="list"
          data-drop-date=""
          data-drop-key={IDEAS}
          ondragover={(e) => { e.preventDefault(); dropTarget = IDEAS; }}
          ondragleave={() => { if (dropTarget === IDEAS) dropTarget = null; }}
          ondrop={(e) => { e.preventDefault(); dropOn(null, null); }}
        >
          <h2>💡 {$t('organizer.ideas')}</h2>
          <p class="hint">{$t('organizer.ideas_hint')}</p>
          {#each ideas as item (item.id)}
            {@render planItem(item, null)}
          {/each}
          <form class="draft-form" onsubmit={(e) => { e.preventDefault(); addItem(null); }}>
            <input
              class="item-draft"
              placeholder={$t('organizer.add_idea')}
              bind:value={drafts[IDEAS]}
              enterkeyhint="done"
              onblur={() => addItem(null)}
            />
          </form>
        </section>


        <section class="panel">
          <h2>✅ {$t('organizer.before_trip')}</h2>
          {#each tasks as task (task.id)}
            <div class="task" class:done={task.done}>
              <input type="checkbox" checked={task.done} onchange={() => toggleTask(task)} />
              <span class="task-text">{task.text}</span>
              <select
                class="assignee"
                value={personKey(task.assignee_type, task.assignee_id)}
                onchange={(e) => {
                  const el = e.currentTarget as HTMLSelectElement;
                  if (el.value === NEW_PERSON) {
                    el.value = personKey(task.assignee_type, task.assignee_id);
                    newPersonFor = task.id;
                  } else {
                    assign(task, el.value);
                  }
                }}
              >
                <option value="">—</option>
                {#each people as p (personKey(p.type, p.id))}
                  <option value={personKey(p.type, p.id)}>{p.name}</option>
                {/each}
                <option value={NEW_PERSON}>{$t('organizer.add_person')}</option>
              </select>
              <button class="icon-btn" aria-label={$t('organizer.remove')} onclick={() => deleteTask(task)}>×</button>
            </div>
            {#if newPersonFor === task.id}
              <!-- svelte-ignore a11y_autofocus -->
              <input
                class="item-draft new-person"
                placeholder={$t('organizer.person_name')}
                bind:value={newPersonName}
                autofocus
                onkeydown={(e) => {
                  if (e.key === 'Enter') addPerson(task);
                  if (e.key === 'Escape') newPersonFor = null;
                }}
                onblur={() => addPerson(task)}
              />
            {/if}
          {/each}
          <form class="draft-form" onsubmit={(e) => { e.preventDefault(); addTask(); }}>
            <input
              class="item-draft"
              placeholder={$t('organizer.add_task')}
              bind:value={taskDraft}
              enterkeyhint="done"
              onblur={() => addTask()}
            />
          </form>
        </section>
      </aside>
    </div>

    <div
      class="modal-backdrop"
      class:closed={!stayFormOpen && !legFormOpen}
      role="presentation"
      onclick={closeBookingEditors}
    >
      <div
        class="modal booking-modal"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        onclick={(e) => e.stopPropagation()}
        onkeydown={trapTab}
      >
        <button class="modal-close" type="button" aria-label={$t('organizer.close')} onclick={closeBookingEditors}>✕</button>
        <TripStays
          bind:this={staysEditor}
          editorOnly
          {trip}
          {flights}
          {segments}
          onchange={(list) => (stays = list)}
          onformchange={(open) => (stayFormOpen = open)}
        />
        <TripTransport
          bind:this={legsEditor}
          editorOnly
          {trip}
          {flights}
          onchange={(list) => (segments = list)}
          onformchange={(open) => (legFormOpen = open)}
        />
      </div>
    </div>

    {#if editing}
      <div class="modal-backdrop" role="presentation" onclick={() => (editing = null)}>
        <div
          class="modal"
          role="dialog"
          aria-modal="true"
          tabindex="-1"
          onclick={(e) => e.stopPropagation()}
          onkeydown={trapTab}
          use:dialogFocus
        >
        <button class="modal-close" type="button" aria-label={$t('organizer.close')} onclick={() => (editing = null)}>✕</button>
        <form class="modal-form" onsubmit={(e) => { e.preventDefault(); saveEditing(); }}>
          <label class="field">
            <span class="form-label">{$t('organizer.item_title')}</span>
            <input class="form-input" bind:value={editing.title} required />
          </label>
          <div class="field">
            <span class="form-label">{$t('organizer.place')}</span>
            <PlaceInput
              kind="poi"
              near={routeCenter}
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
                  <option value={d}>{weekday(d)} {dayMonth(d)}</option>
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
            <textarea class="form-input" rows="4" bind:value={editing.notes}></textarea>
          </label>
          <div class="form-actions">
            <button class="btn btn-primary btn-sm" type="submit">{$t('organizer.save')}</button>
            <button class="btn btn-secondary btn-sm" type="button" onclick={() => (editing = null)}>{$t('organizer.cancel')}</button>
            <button class="btn btn-danger btn-sm modal-delete" type="button" onclick={() => editing && deleteItem(editing)}>{$t('organizer.remove')}</button>
          </div>
        </form>
        </div>
      </div>
    {/if}
  {/if}
</div>

{#if touchGhost}
  <div class="touch-ghost" style="left:{touchGhost.x}px; top:{touchGhost.y}px">{touchGhost.title}</div>
{/if}

{#snippet ideaPicker(date: string)}
  {#if itemsOn(null).length}
    <select
      class="idea-pick"
      aria-label={$t('organizer.pick_idea')}
      value=""
      onchange={(e) => { const el = e.currentTarget; scheduleIdea(el.value, date); el.value = ''; }}
    >
      <option value="">💡 {$t('organizer.pick_idea')}</option>
      {#each itemsOn(null) as idea (idea.id)}
        <option value={idea.id}>{idea.lat != null ? '📍' : '💡'} {idea.title}</option>
      {/each}
    </select>
  {/if}
{/snippet}

{#snippet planItem(item: PlanItem, date: string | null)}
  <div
    class="item status-{item.status}"
    class:dragging={dragId === item.id}
    draggable={touchOnly ? 'false' : 'true'}
    role="listitem"
    data-item-id={item.id}
    data-drop-date={date ?? ''}
    data-drop-key={date ?? IDEAS}
    {@attach touchDraggable(item)}
    ondragstart={(e) => { dragId = item.id; e.dataTransfer?.setData('text/plain', item.id); }}
    ondragend={() => { dragId = null; dropTarget = null; }}
    ondragover={(e) => { e.preventDefault(); dropTarget = date ?? IDEAS; }}
    ondrop={(e) => { e.preventDefault(); e.stopPropagation(); dropOn(date, item.id); }}
  >
    <button
      class="status-dot"
      title={$t(`organizer.status_${item.status}`)}
      aria-label={$t(`organizer.status_${item.status}`)}
      onclick={() => cycleStatus(item)}
    ></button>
    <button class="item-body" onclick={() => (editing = { ...item })}>
      {#if item.time}<span class="item-time">{item.time}</span>{/if}
      <span class="item-title">{item.title}</span>
      {#if item.notes}<span class="item-has-notes" title={item.notes}>📝</span>{/if}
      {#if item.place_name}
        {@const n = mapNumber(item, date)}
        <span class="item-place">📍 {#if n}<b>{n}</b> · {/if}{item.place_name}</span>
      {/if}
    </button>
  </div>
{/snippet}

<style>
  .planner-page {
    padding: var(--space-md) var(--space-lg) var(--space-xl);
    max-width: none;
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
  }
  .stats strong {
    color: var(--text-primary);
    font-size: 1.05rem;
  }
  .stats .warn strong {
    color: var(--warning-text, var(--warning));
  }
  h2 {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    margin: 0 0 var(--space-sm);
  }
  .muted {
    color: var(--text-muted);
  }
  .small {
    font-size: 0.75rem;
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
    align-items: baseline;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--stop) 50%, transparent);
    background: color-mix(in srgb, var(--stop) 12%, var(--bg-card));
    color: var(--text-primary);
    cursor: pointer;
    font: inherit;
  }
  .stop-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--stop);
    align-self: center;
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
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: var(--space-md);
    align-items: start;
  }
  .workspace.side-hidden {
    grid-template-columns: minmax(0, 1fr);
  }
  .side[hidden] {
    display: none;
  }
  .stats {
    align-items: center;
  }
  .side-toggle {
    white-space: nowrap;
  }
  .board-empty {
    padding: var(--space-lg);
  }
  .board {
    display: grid;
    grid-template-columns: 96px repeat(var(--cols), 190px);
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--bg-card);
    /* No height cap: the board grows with its busiest day and the page scrolls.
       A capped board scrolled inside itself, which hid the notes row and the
       bottom of the city frames below a scrollbar that was easy to miss. */
  }
  .lane-label,
  .day-head,
  .cell {
    border-right: 1px solid var(--border-light, var(--border));
    border-bottom: 1px solid var(--border-light, var(--border));
    padding: 8px;
    min-width: 0;
  }
  .lane-label {
    position: sticky;
    left: 0;
    z-index: 2;
    background: var(--bg-secondary, var(--bg-card));
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }
  .corner {
    top: 0;
    z-index: 3;
  }
  .day-head {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--bg-secondary, var(--bg-card));
    display: flex;
    flex-direction: column;
  }
  button.day-head {
    appearance: none;
    font: inherit;
    color: inherit;
    text-align: left;
    border-top: 0;
    border-left: 0;
    cursor: pointer;
  }
  .cell[style*='--frame'] {
    box-shadow: var(--frame-shadow);
    background: color-mix(in srgb, var(--frame) 6%, transparent);
  }
  .day-head[style*='--frame'] {
    box-shadow: var(--frame-shadow);
    background: color-mix(in srgb, var(--frame) 16%, var(--bg-secondary, var(--bg-card)));
  }
  .day-head.focused,
  .day-head.focused[style*='--frame'] {
    box-shadow: var(--frame-shadow, inset 0 0 0 transparent), inset 0 -4px 0 var(--accent);
    background: color-mix(in srgb, var(--accent) 18%, var(--bg-secondary, var(--bg-card)));
  }
  .day-head.weekend {
    background: color-mix(in srgb, var(--accent) 8%, var(--bg-secondary, var(--bg-card)));
  }
  .day-num {
    font-size: 0.7rem;
    color: var(--text-muted);
  }
  .day-date {
    font-weight: 600;
  }
  .city-cell {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .city-tag {
    font-size: 0.78rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--stop) 18%, transparent);
    border-left: 3px solid var(--stop);
  }
  .stay {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .move,
  .stay,
  .no-stay {
    font-size: 0.78rem;
    line-height: 1.35;
    margin-bottom: 4px;
  }
  .move-time {
    font-family: var(--font-mono);
    color: var(--text-secondary);
  }
  .no-stay {
    color: var(--warning-text, var(--warning));
  }
  .items-cell {
    min-height: 120px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .drop {
    outline: 2px dashed var(--accent);
    outline-offset: -3px;
  }
  .item {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 5px 6px;
    border-radius: var(--radius-sm);
    background: var(--bg-subtle, var(--surface-alt));
    border: 1px solid var(--border-light, var(--border));
    cursor: grab;
  }
  .item.dragging {
    opacity: 0.4;
  }
  .status-dot {
    flex: none;
    width: 12px;
    height: 12px;
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
    font-size: 0.8rem;
    line-height: 1.35;
    cursor: pointer;
    overflow-wrap: anywhere;
  }
  .item-time {
    font-family: var(--font-mono);
    color: var(--text-secondary);
    margin-right: 4px;
  }
  .item-has-notes {
    margin-left: 4px;
    font-size: 0.7rem;
  }
  /* A form, not a keydown on Enter: some phone keyboards (Samsung's,
     Gboard mid-word) report the key as "Unidentified", and the keyboard's
     own Done/Go button submits a form whatever it reports. */
  .draft-form {
    display: contents;
  }
  .touch-ghost {
    position: fixed;
    z-index: 1000;
    pointer-events: none;
    transform: translate(-50%, -120%);
    max-width: 70vw;
    padding: 6px 10px;
    border-radius: var(--radius-sm);
    background: var(--surface);
    border: 1px solid var(--accent);
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.25);
    font-size: 0.85rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  @media (hover: none) {
    .item {
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      user-select: none;
    }
  }
  .idea-pick {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: 0.8rem;
    padding: 4px 6px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
  }
  .item-draft {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: 0.8rem;
    padding: 5px 6px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-primary);
  }
  .item-draft:focus {
    outline: none;
    border-style: solid;
    border-color: var(--accent);
  }
  .note {
    width: 100%;
    box-sizing: border-box;
    resize: vertical;
    font: inherit;
    font-size: 0.78rem;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-primary);
  }
  .note:focus {
    outline: none;
    border-color: var(--accent);
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
  }
  .panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-md);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .hint {
    margin: -4px 0 4px;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .task {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.82rem;
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
    /* Above the app's tab bar (120) and side rail, which otherwise cover the
       dialog's buttons on a phone. */
    z-index: 500;
    padding: 16px 0;
  }
  .modal {
    position: relative;
    max-height: calc(100dvh - 32px);
    overflow-y: auto;
    background: var(--bg-card);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    width: min(440px, calc(100vw - 32px));
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
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
  }
  @media (max-width: 900px) {
    .planner-page {
      padding: var(--space-md);
    }
    .workspace {
      grid-template-columns: 1fr;
    }
  }

  /* Phone: days as stacked cards, framed in their city's colour. */
  .day-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }
  .day-card-m {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 5px solid var(--frame, var(--border));
    border-radius: var(--radius-md);
    overflow: hidden;
  }
  .dm-head {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: 8px 10px;
    background: color-mix(in srgb, var(--frame, transparent) 12%, var(--bg-card));
  }
  .dm-head > div:first-child {
    display: flex;
    flex-direction: column;
  }
  .dm-date {
    font-weight: 700;
  }
  .dm-cities {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    flex: 1;
    justify-content: flex-end;
  }
  .dm-map {
    border: 1px solid var(--border);
    background: var(--bg-card);
    border-radius: var(--radius-sm);
    font-size: 1rem;
    padding: 4px 8px;
    cursor: pointer;
  }
  .dm-map.on {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 15%, var(--bg-card));
  }
  .dm-section {
    padding: 6px 10px;
    border-top: 1px solid var(--border-light, var(--border));
  }
  .dm-items {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .dm-note {
    display: block;
    width: 100%;
    border-top: 1px solid var(--border-light, var(--border));
    border-radius: 0;
    padding: 8px 10px;
    min-height: 44px;
  }
  @media (max-width: 760px) {
    .planner-page {
      padding: var(--space-sm) var(--space-sm) var(--space-xl);
    }
    .panel,
    .route {
      padding: 12px;
    }
    .dm-head,
    .dm-section {
      padding-left: 10px;
      padding-right: 10px;
    }
    .plan-header {
      align-items: flex-start;
    }
    .plan-header h1 {
      font-size: 1.3rem;
    }
    .autosave,
    .side-toggle {
      display: none;
    }
    .save-box {
      margin-left: 0;
    }
    .stats {
      gap: var(--space-sm);
      font-size: 0.78rem;
    }
    .route {
      padding: var(--space-sm);
    }
    .stop-chip {
      padding: 4px 10px;
    }
    .stop-form .field {
      flex: 1 1 140px;
    }
    .map-box {
      height: 340px;
    }
    .map-head {
      flex-wrap: wrap;
      gap: var(--space-xs);
    }
    .item-body,
    .item-draft,
    .idea-pick,
    .note {
      font-size: 16px; /* below 16px iOS zooms in on focus */
    }
    .editable {
      font-size: 0.85rem;
      padding: 6px 4px;
    }
    .modal {
      padding: var(--space-md);
    }
    .row {
      flex-wrap: wrap;
    }
    .row .field {
      flex: 1 1 120px;
    }
  }
  .item-place {
    display: block;
    font-size: 0.72rem;
    color: var(--text-secondary);
    margin-top: 2px;
  }
  .map-section {
    min-width: 0;
  }
  .main-col {
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
    min-width: 0;
  }
  .map-head {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    margin-bottom: var(--space-sm);
  }
  .map-head h2 {
    margin: 0;
  }
  .map-head .hint {
    flex: 1;
    margin: 0;
  }
  .map-box {
    height: 480px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  .place-search {
    margin-top: 2px;
  }
  .new-person {
    margin-left: 22px;
    width: calc(100% - 22px);
  }
  .editable {
    display: block;
    width: 100%;
    text-align: left;
    font: inherit;
    font-size: 0.78rem;
    color: inherit;
    text-decoration: none;
    background: none;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    padding: 2px 4px;
    margin: 0 -4px 4px;
    cursor: pointer;
  }
  .editable:hover {
    border-color: var(--border);
    background: var(--bg-card);
  }
  .no-stay.editable {
    color: var(--warning-text, var(--warning));
  }
  .cell-add {
    display: inline-block;
    font: inherit;
    font-size: 0.72rem;
    color: var(--text-muted);
    background: none;
    border: none;
    padding: 0;
    text-decoration: none;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.1s;
  }
  .cell:hover .cell-add,
  .cell-add:focus-visible {
    opacity: 1;
  }
  .save-box {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    margin-left: auto;
  }
  .autosave {
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .autosave.failed {
    color: var(--warning-text, var(--warning));
  }
  .modal-backdrop.closed {
    display: none;
  }
  .booking-modal {
    padding-top: 48px;
    width: min(640px, calc(100vw - 32px));
    max-height: calc(100vh - 64px);
    overflow-y: auto;
  }
  .modal-close {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 1;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: var(--text-muted);
    font-size: 1.05rem;
    cursor: pointer;
  }
  .modal-close:hover {
    background: var(--bg-subtle, var(--surface-alt));
    color: var(--text-primary);
  }
  /* The item dialog's first field sits under the close button otherwise. */
  .modal-form {
    padding-top: 18px;
  }
  .modal-delete {
    margin-left: auto;
  }
  .dm-add-transport {
    display: inline-block;
    font-size: 0.8rem;
    color: var(--text-muted);
    text-decoration: none;
    padding: 4px 0;
  }
</style>
