<script lang="ts">
  import type { TripSegment, SegmentType } from '../api/types';
  import { formatTime, formatDate, formatDuration } from '../lib/utils';

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
  <div class="flight-row-route" style="flex:1">
    <div class="flight-route segment-route">
      <span>{s.departure.name}</span>
      <span class="flight-route-arrow">→</span>
      <span>{s.arrival.name}</span>
    </div>
    <div class="flight-time">
      {formatTime(s.departure_datetime, s.departure.timezone)} → {formatTime(s.arrival_datetime, s.arrival.timezone)}
      <span style="color:var(--text-muted);margin-left:4px">{formatDate(s.departure_datetime)}</span>
    </div>
  </div>
  <div class="flight-meta">
    <span class="segment-type-badge">{TYPE_ICONS[s.type] ?? '🚆'}</span>
    {#if label}
      <div style="margin-top:4px">{label}</div>
    {/if}
    {#if duration}
      <div style="color:var(--text-muted)">{duration}</div>
    {/if}
    {#if s.seat}
      <div style="color:var(--text-muted)">{s.seat}</div>
    {/if}
  </div>
</button>

<style>
  /* Reuses .flight-row from app.css so ground legs sit flush with flights in
     the same list. Only the button defaults are reset — notably NOT the border,
     which .flight-row supplies and which is what makes the row read as a card. */
  .segment-row-btn {
    width: 100%;
    font: inherit;
    text-align: left;
    cursor: pointer;
    align-items: flex-start;
  }

  /* Station names are far longer than IATA codes and must be allowed to wrap. */
  .segment-route {
    flex-wrap: wrap;
  }

  .segment-type-badge {
    font-size: 1rem;
    line-height: 1;
  }
</style>
