<script lang="ts">
  import type { TripStay, StayKind } from '../api/types';
  import { formatDate } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    stay: TripStay;
    /** Opens the inline editor. A stay has no detail page of its own — there is
     * no live status or boarding pass to hang one off — so the card is a button,
     * the same shape SegmentRow uses. */
    onedit: (stay: TripStay) => void;
    /** Set when the stay does not overlap the trip's transport at all; rendered
     * as a warning, never as a blocked save. */
    warning?: string | null;
  }

  const { stay, onedit, warning = null }: Props = $props();

  const KIND_ICONS: Record<StayKind, string> = {
    hotel: '🏨',
    airbnb: '🏡',
    hostel: '🛏️',
    other: '📍',
  };

  /** Locale files carry a `_plural` twin per counted string, matching the
   * convention the rest of the catalogue uses. */
  function plural(key: string, count: number): string {
    return $t(count === 1 ? key : `${key}_plural`, { values: { count } });
  }

  const nightsLabel = $derived(
    stay.nights === null
      ? null
      : stay.nights === 0
        ? $t('stays.day_use')
        : plural('stays.nights', stay.nights),
  );
  const details = $derived(
    [stay.room_type, stay.guests ? plural('stays.guests_n', stay.guests) : null]
      .filter(Boolean)
      .join(' · '),
  );
</script>

<button type="button" class="stay-row" onclick={() => onedit(stay)}>
  <span class="stay-icon">{KIND_ICONS[stay.kind] ?? '📍'}</span>
  <span class="stay-body">
    <span class="stay-name">{stay.place.name}</span>
    <span class="stay-dates">
      {formatDate(stay.check_in_date)} → {formatDate(stay.check_out_date)}
      {#if nightsLabel}<span class="stay-nights">· {nightsLabel}</span>{/if}
    </span>
    {#if stay.place.address}
      <span class="stay-address">{stay.place.address}</span>
    {/if}
    {#if details}
      <span class="stay-address">{details}</span>
    {/if}
    {#if stay.booking_reference}
      <span class="stay-address">{$t('stays.booking_ref')}: {stay.booking_reference}</span>
    {/if}
    {#if warning}
      <span class="stay-warning">⚠ {warning}</span>
    {/if}
  </span>
</button>

<style>
  /* Not .flight-row: a stay is a block of days rather than a leg, and giving it
     the same row shape as a flight made the two read as interchangeable. */
  .stay-row {
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

  .stay-icon {
    font-size: 1.1rem;
    line-height: 1.3;
  }

  .stay-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .stay-name {
    font-weight: 600;
    font-size: 0.92rem;
    /* Property names are long and must wrap rather than overflow the card. */
    overflow-wrap: anywhere;
  }

  .stay-dates {
    font-size: 0.82rem;
  }

  .stay-nights {
    color: var(--text-muted, #64748b);
  }

  .stay-address {
    font-size: 0.76rem;
    color: var(--text-muted, #64748b);
    overflow-wrap: anywhere;
  }

  .stay-warning {
    margin-top: 2px;
    font-size: 0.76rem;
    color: var(--warning, #b45309);
  }
</style>
