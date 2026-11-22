<script lang="ts">
  import { onMount } from 'svelte';
  import type { Trip, Flight, TripSegment, TripStay, TripCarRental, TripDayNote, PlanItem } from '../api/types';
  import { dayNotesApi, plannerApi } from '../api/client';
  import { parseDayNote } from '../lib/dayNotes';
  import { t } from '../lib/i18n';
  import TripDayCard, { type DayContent } from './TripDayCard.svelte';
  import { legDateKeys, localDateKey } from '../lib/utils';

  interface Props {
    trip: Trip;
    /** Ground legs live outside `trip`, so they are passed in separately. */
    segments?: TripSegment[];
    /** Stays likewise. Unlike flights and segments these are NOT grouped by day
     * here: a stay spans days, so each card picks out the ones covering it. */
    stays?: TripStay[];
    /** Car rentals likewise, and for the same reason: a hire spans days, so
     * each card picks out the ones covering it. */
    carRentals?: TripCarRental[];
    onLoaded?: (contentByDate: Record<string, DayContent>) => void;
    forceExpanded?: boolean;
    onlyDate?: string;
    collapseAll?: boolean;
  }
  const {
    trip,
    segments = [],
    stays = [],
    carRentals = [],
    onLoaded,
    forceExpanded = false,
    onlyDate,
    collapseAll = false,
  }: Props = $props();

  function getDayRange(start: string, end: string): string[] {
    const days: string[] = [];
    const [sy, sm, sd] = start.split('-').map(Number);
    const [ey, em, ed] = end.split('-').map(Number);
    const cur = new Date(sy, sm - 1, sd);
    const endDate = new Date(ey, em - 1, ed);
    while (cur <= endDate) {
      const y = cur.getFullYear();
      const m = String(cur.getMonth() + 1).padStart(2, '0');
      const d = String(cur.getDate()).padStart(2, '0');
      days.push(`${y}-${m}-${d}`);
      cur.setDate(cur.getDate() + 1);
    }
    return days;
  }

  /* A leg goes on **every day it covers**, not only the day it departs. A drive
   * leaving on the 31st and arriving on the 1st used to be filed on the 31st
   * alone, so the day spent on the road had an empty card — and the planner
   * draws one card per day precisely so no day of a trip is blank. Which part
   * of the leg belongs to which day is `legRoleFor`'s job, in the card. */
  function groupByCoveredDays<T>(
    list: T[],
    from: (item: T) => string | null,
    to: (item: T) => string | null,
  ): Map<string, T[]> {
    const map = new Map<string, T[]>();
    for (const item of list) {
      for (const date of legDateKeys(from(item), to(item))) {
        if (!map.has(date)) map.set(date, []);
        map.get(date)!.push(item);
      }
    }
    return map;
  }

  function groupFlightsByDate(flights: Flight[]): Map<string, Flight[]> {
    return groupByCoveredDays(
      flights,
      (f) => localDateKey(f.departure_datetime, f.departure_timezone),
      (f) => localDateKey(f.arrival_datetime, f.arrival_timezone),
    );
  }

  function groupSegmentsByDate(list: TripSegment[]): Map<string, TripSegment[]> {
    return groupByCoveredDays(
      list,
      (s) => localDateKey(s.departure_datetime, s.departure.timezone),
      (s) => localDateKey(s.arrival_datetime, s.arrival.timezone),
    );
  }

  function todayStr(): string {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  }

  const allDays = $derived(
    trip.start_date && trip.end_date ? getDayRange(trip.start_date, trip.end_date) : []
  );
  const days = $derived(onlyDate ? allDays.filter((d) => d === onlyDate) : allDays);
  const flightMap = $derived(groupFlightsByDate(trip.flights ?? []));
  const segmentMap = $derived(groupSegmentsByDate(segments));
  const today = todayStr();

  let contentByDate = $state<Record<string, DayContent>>({});
  /** The planner's items by day: the day cards show and edit the same list
   * the planner does, so what is added on one page is on the other. */
  let itemsByDate = $state<Record<string, PlanItem[]>>({});
  let loaded = $state(false);
  let loadError = $state<string | null>(null);

  onMount(async () => {
    try {
      const [rows, plan]: [TripDayNote[], { items: PlanItem[] } | null] = await Promise.all([
        dayNotesApi.list(trip.id),
        plannerApi.get(trip.id).catch(() => null),
      ]);
      const map: Record<string, DayContent> = {};
      for (const row of rows) map[row.date] = parseDayNote(row.content);
      contentByDate = map;
      const byDate: Record<string, PlanItem[]> = {};
      for (const it of plan?.items ?? []) {
        if (it.date) (byDate[it.date] ??= []).push(it);
      }
      itemsByDate = byDate;
      onLoaded?.(map);
    } catch {
      loadError = 'Failed to load planner notes.';
    }
    loaded = true;
  });
</script>

<div class="planner">
  {#if !trip.start_date || !trip.end_date}
    <p class="planner-empty">{$t('planner.no_dates')}</p>
  {:else if loadError}
    <p class="planner-empty" style="color:var(--danger)">{loadError}</p>
  {:else if !loaded}
    <p class="planner-empty">{$t('planner.loading')}</p>
  {:else}
    {#each days as date (date)}
      <TripDayCard
        tripId={trip.id}
        {date}
        flights={flightMap.get(date) ?? []}
        segments={segmentMap.get(date) ?? []}
        {stays}
        {carRentals}
        initialContent={contentByDate[date] ?? { note: '', items: [] }}
        planItems={itemsByDate[date] ?? []}
        initiallyExpanded={collapseAll ? false : date === today}
        {forceExpanded}
      />
    {/each}
  {/if}
</div>

<style>
  .planner {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .planner-empty {
    color: var(--text-muted);
    font-size: 0.9rem;
    padding: var(--space-md) 0;
  }
</style>
