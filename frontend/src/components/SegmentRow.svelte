<script lang="ts">
  import type { TripSegment, SegmentType } from '../api/types';
  import { formatTime, formatDayMonth, formatDuration } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    segment: TripSegment;
    /** Opens the inline editor. Ground legs have no detail page to link to —
     * unlike a flight, there is no aircraft, live status or boarding pass to
     * show — so the row is a button rather than an anchor. */
    onedit: (segment: TripSegment) => void;
  }

  const { segment: s, onedit }: Props = $props();

  const TYPE_ICONS: Record<SegmentType, string> = {
    train: '🚆',
    bus: '🚌',
    ferry: '⛴️',
    car: '🚗',
  };

  const duration = $derived(formatDuration(s.duration_minutes));
  const label = $derived([s.operator, s.number].filter(Boolean).join(' '));
</script>

<button type="button" class="flight-row segment-row-btn" onclick={() => onedit(s)}>
  <div class="flight-row-clock">
    <span class="flight-row-dep">{formatTime(s.departure_datetime, s.departure.timezone)}</span>
    <span class="flight-row-date">{formatDayMonth(s.departure_datetime)}</span>
  </div>
  <div class="flight-row-route">
    <div class="flight-route segment-route">
      <span>{s.departure.name}</span>
      <span class="flight-route-arrow segment-arrow" aria-hidden="true">→</span>
      <span>{s.arrival.name}</span>
    </div>
    <div class="flight-time">
      <span>{$t('flight.arrives_at', { values: { time: formatTime(s.arrival_datetime, s.arrival.timezone) } })}</span>
      {#if duration}
        <span class="text-muted">{duration}</span>
      {/if}
    </div>
  </div>
  <div class="flight-meta">
    <span class="segment-type-badge">{TYPE_ICONS[s.type] ?? '🚆'}</span>
    {#if label}
      <span>{label}</span>
    {/if}
    {#if s.seat}
      <span class="text-muted">{s.seat}</span>
    {/if}
  </div>
</button>

<style>
  /* Reuses .flight-row from app.css so ground legs sit flush with flights in
     the same list — they are lines on the same board, and a train between two
     flights is part of the same journey. Only the button defaults are reset. */
  .segment-row-btn {
    width: 100%;
    font: inherit;
    text-align: left;
    cursor: pointer;
    align-items: flex-start;
  }

  /* Station names are far longer than IATA codes and must be allowed to wrap,
     so the drawn connector a flight gets cannot stretch between them — and it
     carries an aircraft glyph, which is wrong on a train. Plain arrow instead. */
  .segment-route {
    flex-wrap: wrap;
    font-size: 0.98rem;
  }

  .segment-arrow {
    flex: 0 0 auto;
    max-width: none;
    height: auto;
    background: none;
    font-size: 0.85rem;
    color: var(--text-muted);
  }

  .segment-arrow::after {
    content: none;
  }

  .segment-type-badge {
    font-size: 1rem;
    line-height: 1;
  }
</style>
