<script lang="ts">
  import type { Flight } from '../api/types';
  import { formatTime, formatDate, formatDuration, flightStatus } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    flight: Flight;
  }
  const { flight: f }: Props = $props();

  const status = $derived(flightStatus(f));
  const duration = $derived(formatDuration(f.duration_minutes));
</script>

<a class="flight-row flight-row-{status}" href="#/trips/{f.trip_id}/flights/{f.id}">
  <div class="flight-row-route" style="flex:1">
    <div class="flight-route">
      <span>{f.departure_airport}</span>
      <span class="flight-route-arrow">→</span>
      <span>{f.arrival_airport}</span>
    </div>
    <div class="flight-time">
      {formatTime(f.departure_datetime, f.departure_timezone)} → {formatTime(f.arrival_datetime, f.arrival_timezone)}
      <span style="color:var(--text-muted);margin-left:4px">{formatDate(f.departure_datetime)}</span>
    </div>
  </div>
  <div class="flight-meta">
    {#if f.airline_code}
      <span class="airline-badge airline-{f.airline_code}">{f.airline_code}</span>
    {/if}
    <div style="margin-top:4px">{f.flight_number}</div>
    {#if duration}
      <div style="color:var(--text-muted)">{duration}</div>
    {/if}
    {#if status === 'completed'}
      <span class="flight-status-badge flight-status-completed">✓</span>
    {:else if status === 'active'}
      <span class="flight-status-badge flight-status-active">{$t('flight.in_flight')}</span>
    {/if}
  </div>
</a>
