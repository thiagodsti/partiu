<script lang="ts">
  import type { TripCarRental } from '../api/types';
  import { formatDate, formatTime } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    rental: TripCarRental;
    /** Opens the inline editor. A rental has no detail page of its own — there
     * is no live status or boarding pass to hang one off — so the card is a
     * button, the same shape StayRow and SegmentRow use. */
    onedit: (rental: TripCarRental) => void;
  }

  const { rental, onedit }: Props = $props();

  function plural(key: string, count: number): string {
    return $t(count === 1 ? key : `${key}_plural`, { values: { count } });
  }

  const daysLabel = $derived(
    rental.days === null || rental.days === 0 ? null : plural('car_rentals.days', rental.days),
  );

  /* One place for a return hire, an arrow for a one-way. Printing "Vienna →
   * Vienna" on the common case is the same noise TripCard's routing line
   * suppresses when a trip's two ends agree. */
  const where = $derived(
    rental.is_one_way
      ? `${rental.pickup.name} → ${rental.dropoff.name}`
      : rental.pickup.name,
  );

  /* Both counter appointments, because both are deadlines: the pickup time is
   * binding at most vendors and a late return is charged. Times are shown in
   * each counter's own zone — a one-way hire can cross one. */
  const window = $derived(
    `${formatDate(rental.pickup_date)} ${formatTime(rental.pickup_datetime, rental.pickup.timezone)}` +
      ` → ${formatDate(rental.dropoff_date)} ${formatTime(rental.dropoff_datetime, rental.dropoff.timezone)}`,
  );
</script>

<button type="button" class="rental-row" onclick={() => onedit(rental)}>
  <span class="rental-icon">🚗</span>
  <span class="rental-body">
    <span class="rental-vendor">{rental.vendor}</span>
    <span class="rental-where">{where}</span>
    <span class="rental-window">
      {window}
      {#if daysLabel}<span class="rental-days">· {daysLabel}</span>{/if}
    </span>
    {#if rental.vehicle}
      <span class="rental-detail">{rental.vehicle}</span>
    {/if}
    {#if rental.booking_reference}
      <span class="rental-detail">
        {$t('car_rentals.booking_ref')}: <span class="rental-ref">{rental.booking_reference}</span>
      </span>
    {/if}
  </span>
</button>

<style>
  /* Shares StayRow's block shape rather than .flight-row: like a stay, a rental
     is a span you hold rather than a line on a departures board, and giving it
     a leg's row shape would make the two read as interchangeable. */
  .rental-row {
    display: flex;
    gap: 10px;
    width: 100%;
    padding: 10px 12px;
    margin-bottom: var(--space-sm, 8px);
    border: 1px solid var(--border, #e2e8f0);
    border-radius: var(--radius-md, 8px);
    background: var(--surface, #fff);
    font: inherit;
    color: var(--text, inherit);
    text-align: left;
    cursor: pointer;
  }

  .rental-icon {
    font-size: 1.1rem;
    line-height: 1.3;
  }

  .rental-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .rental-vendor {
    font-weight: 600;
    font-size: 0.92rem;
    overflow-wrap: anywhere;
  }

  .rental-where {
    font-size: 0.82rem;
    overflow-wrap: anywhere;
  }

  .rental-window {
    font-size: 0.82rem;
  }

  .rental-days {
    color: var(--text-muted, #64748b);
  }

  .rental-detail {
    font-size: 0.76rem;
    color: var(--text-muted, #64748b);
    overflow-wrap: anywhere;
  }

  /* A booking reference is a code, so it gets the ticket face — the same rule
     flight numbers and IATA pairs follow. */
  .rental-ref {
    font-family: var(--font-mono);
  }
</style>
