<script lang="ts">
  import type { Flight } from '../api/types';
  import { formatTime, formatDayMonth, formatDuration, flightStatus } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    flight: Flight;
    basePath?: string;
  }
  const { flight: f, basePath = 'trips' }: Props = $props();

  const status = $derived(flightStatus(f));
  const duration = $derived(formatDuration(f.duration_minutes));

  const isCancelled = $derived(f.live_status === 'cancelled');
  const isDiverted = $derived(f.live_status === 'diverted');
  const depDelay = $derived((f.live_departure_delay ?? 0) > 0 ? f.live_departure_delay : null);
</script>

<a class="flight-row flight-row-{isCancelled ? 'cancelled' : status}" href="#/{basePath}/{f.trip_id}/flights/{f.id}">
  <!-- Departure time leads the row, the way it leads a line on a board. -->
  <div class="flight-row-clock">
    <span class="flight-row-dep">{formatTime(f.departure_datetime, f.departure_timezone)}</span>
    <span class="flight-row-date">{formatDayMonth(f.departure_datetime)}</span>
  </div>
  <div class="flight-row-route">
    <div class="flight-route">
      <span>{f.departure_airport}</span>
      <span class="flight-route-arrow" aria-hidden="true"></span>
      <span>{f.arrival_airport}</span>
    </div>
    <div class="flight-time">
      <span>{$t('flight.arrives_at', { values: { time: formatTime(f.arrival_datetime, f.arrival_timezone) } })}</span>
      {#if duration}
        <span class="text-muted">{duration}</span>
      {/if}
    </div>
  </div>
  <div class="flight-meta">
    {#if f.airline_code}
      <span class="airline-badge airline-{f.airline_code}">{f.airline_code}</span>
    {/if}
    <span class="flight-number">{f.flight_number}</span>
    {#if isCancelled}
      <span class="flight-status-badge flight-status-cancelled">{$t('flight.live_status_cancelled')}</span>
    {:else if isDiverted}
      <span class="flight-status-badge flight-status-diverted">{$t('flight.live_status_diverted')}</span>
    {:else if depDelay}
      <span class="flight-status-badge flight-status-delayed">+{depDelay}min</span>
    {:else if status === 'completed'}
      <span class="flight-status-badge flight-status-completed">✓</span>
    {:else if status === 'active'}
      <span class="flight-status-badge flight-status-active">{$t('flight.in_flight')}</span>
    {/if}
  </div>
</a>
