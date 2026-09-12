<script lang="ts">
  import { onMount } from 'svelte';
  import type { Trip, Flight, TripSegment, TripStay, TripDayNote } from '../api/types';
  import { dayNotesApi } from '../api/client';
  import { t } from '../lib/i18n';
  import TripDayCard, { type DayContent } from './TripDayCard.svelte';

  interface Props {
    trip: Trip;
    /** Ground legs live outside `trip`, so they are passed in separately. */
    segments?: TripSegment[];
    /** Stays likewise. Unlike flights and segments these are NOT grouped by day
     * here: a stay spans days, so each card picks out the ones covering it. */
    stays?: TripStay[];
    onLoaded?: (contentByDate: Record<string, DayContent>) => void;
    forceExpanded?: boolean;
    onlyDate?: string;
    collapseAll?: boolean;
  }
  const {
    trip,
    segments = [],
    stays = [],
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

  function flightLocalDate(f: Flight): string | null {
    if (!f.departure_datetime) return null;
    try {
      return new Date(f.departure_datetime).toLocaleDateString('en-CA', {
        timeZone: f.departure_timezone ?? undefined,
      });
    } catch {
      return f.departure_datetime.slice(0, 10);
    }
  }

  function groupFlightsByDate(flights: Flight[]): Map<string, Flight[]> {
    const map = new Map<string, Flight[]>();
    for (const f of flights) {
      const date = flightLocalDate(f);
      if (!date) continue;
      if (!map.has(date)) map.set(date, []);
      map.get(date)!.push(f);
    }
    return map;
  }

  /** A leg belongs to the day it departs *locally*, not in UTC — a 08:00
   * Beijing departure is 00:00Z and would otherwise land on the right day only
   * by luck. Mirrors flightLocalDate, but the zone comes from the station. */
  function segmentLocalDate(s: TripSegment): string | null {
    if (!s.departure_datetime) return null;
    try {
      return new Date(s.departure_datetime).toLocaleDateString('en-CA', {
        timeZone: s.departure.timezone ?? undefined,
      });
    } catch {
      return s.departure_datetime.slice(0, 10);
    }
  }

  function groupSegmentsByDate(list: TripSegment[]): Map<string, TripSegment[]> {
    const map = new Map<string, TripSegment[]>();
    for (const s of list) {
      const date = segmentLocalDate(s);
      if (!date) continue;
      if (!map.has(date)) map.set(date, []);
      map.get(date)!.push(s);
    }
    return map;
  }

  function parseContent(raw: string): DayContent {
    if (!raw) return { note: '', items: [] };
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return { note: parsed.note ?? '', items: parsed.items ?? [] };
      }
      // Legacy block array
      if (Array.isArray(parsed)) {
        const textBlock = parsed.find((b: { type: string }) => b.type === 'text');
        const checkBlock = parsed.find((b: { type: string }) => b.type === 'checklist');
        return { note: textBlock?.value ?? '', items: checkBlock?.items ?? [] };
      }
    } catch {
      return { note: raw, items: [] };
    }
    return { note: '', items: [] };
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
  let loaded = $state(false);
  let loadError = $state<string | null>(null);

  onMount(async () => {
    try {
      const rows: TripDayNote[] = await dayNotesApi.list(trip.id);
      const map: Record<string, DayContent> = {};
      for (const row of rows) map[row.date] = parseContent(row.content);
      contentByDate = map;
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
        initialContent={contentByDate[date] ?? { note: '', items: [] }}
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
