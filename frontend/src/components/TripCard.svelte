<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Trip } from '../api/types';
  import { formatDateRange } from '../lib/utils';
  import { t } from '../lib/i18n';

  /**
   * A trip, read as a luggage tag: the destination photo printed down the
   * left edge as a narrow strip, the name and dates on the stub, and a
   * status stripe on the outer edge.
   *
   * It is a horizontal band rather than a photo-on-top card because the
   * thing you scan a list of trips for is the *name*, and stacked cards put
   * a 130px image between every pair of them.
   */
  interface Props {
    trip: Trip;
    href: string;
    imageUrl: string;
    imgFailed: boolean;
    refreshing: boolean;
    showStars?: boolean;
    /** Drives the edge stripe's colour; the badge snippet still supplies the words. */
    status?: 'upcoming' | 'ongoing' | 'completed';
    onImageError: (e: Event) => void;
    onRefreshImage: (e: MouseEvent) => void;
    badge: Snippet;
    footer?: Snippet;
  }

  const { trip, href, imageUrl, imgFailed, refreshing, showStars = false, status = 'upcoming', onImageError, onRefreshImage, badge, footer }: Props = $props();

  const dateRange = $derived(formatDateRange(trip.start_date, trip.end_date));
  const flightCount = $derived(trip.flight_count ?? 0);
  const segmentCount = $derived(trip.segment_count ?? 0);
  const stayCount = $derived(trip.stay_count ?? 0);
  const segmentTypes = $derived(trip.segment_types ?? []);

  const SEGMENT_ICONS: Record<string, string> = {
    train: '🚆',
    bus: '🚌',
    ferry: '⛴️',
    car: '🚗',
  };

  function plural(key: string, n: number): string {
    return $t(n === 1 ? key : `${key}_plural`, { values: { n } });
  }

  /**
   * What the trip is made of, as icon + count chips.
   *
   * A trip of two trains used to read "✈ 0 flights", which is technically true
   * and useless. Each kind is counted separately rather than summed into
   * "3 legs" because the icons are the fastest way to see what a trip *is*.
   *
   * Ground legs name their type only when the trip uses exactly one kind —
   * a train-plus-ferry trip gets the generic label, since no single icon
   * honestly represents it.
   */
  const contents = $derived.by((): string[] => {
    const parts: string[] = [];
    if (flightCount > 0 || (segmentCount === 0 && stayCount === 0)) {
      // The flight chip stays on an empty trip: "0 flights" is the right
      // prompt when a trip genuinely has nothing on it yet.
      parts.push(`✈ ${plural('trips.flight_count', flightCount)}`);
    }
    if (segmentCount > 0) {
      const onlyType = segmentTypes.length === 1 ? segmentTypes[0] : null;
      const icon = onlyType ? (SEGMENT_ICONS[onlyType] ?? '🚆') : '🚆';
      const label = onlyType
        ? plural(`trips.segment_count_${onlyType}`, segmentCount)
        : plural('trips.segment_count', segmentCount);
      parts.push(`${icon} ${label}`);
    }
    if (stayCount > 0) {
      parts.push(`🛏 ${plural('trips.stay_count', stayCount)}`);
    }
    return parts;
  });
  const refs = $derived((trip.booking_refs ?? []).join(', '));
  const showStarRow = $derived(showStars || !!trip.rating);

  /**
   * The routing line a bag tag prints. Only shown when the two ends differ:
   * `_recompute_span` sets destination to the *final* arrival, so a round
   * trip has origin === destination and "GRU → GRU" would be noise.
   */
  const routing = $derived(
    trip.origin_airport && trip.destination_airport && trip.origin_airport !== trip.destination_airport
      ? `${trip.origin_airport} → ${trip.destination_airport}`
      : (trip.origin_airport ?? null),
  );

  const expenseTotals = $derived(
    Object.entries(trip.expenses_total ?? {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([currency, total]) => {
        const s = total % 1 === 0
          ? total.toLocaleString()
          : total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return `${currency} ${s}`;
      })
  );

  function starFill(star: number, rating: number | null | undefined): '100%' | '50%' | '0%' {
    const r = rating ?? 0;
    if (r >= star) return '100%';
    if (r >= star - 0.5) return '50%';
    return '0%';
  }
</script>

<a class="card-link" {href}>
  <article class="card trip-card" data-status={status}>
    <div class="trip-card-cover" class:no-image={imgFailed}>
      {#if imgFailed}
        <span class="trip-card-no-image-icon">✈</span>
      {:else}
        <img
          src={imageUrl}
          alt=""
          class="trip-card-cover-img"
          loading="lazy"
          decoding="async"
          onerror={onImageError}
        />
      {/if}
      <button
        class="trip-card-img-refresh"
        title={$t('trips.refresh_image')}
        disabled={refreshing}
        onclick={onRefreshImage}
      >
        {refreshing ? '…' : '↻'}
      </button>
    </div>

    <div class="trip-card-body">
      <div class="trip-card-main">
        <div class="trip-card-header">
          <h2 class="trip-card-title">{trip.name}</h2>
        </div>

        {#if dateRange}
          <div class="trip-card-meta">
            <span class="trip-card-dates">{dateRange}</span>
            {#if routing}
              <span class="trip-card-route">{routing}</span>
            {/if}
            {#each contents as part}
              <span>{part}</span>
            {/each}
          </div>
        {/if}

        <div class="trip-card-footer">
          {#if refs}
            <span class="text-sm text-muted">{$t('trips.ref', { values: { refs } })}</span>
          {/if}
          {#if showStarRow}
            <span class="trip-card-stars" aria-label={$t('trips.rating_label')}>
              {#each [1,2,3,4,5] as star}
                <span class="star-display" style="--fill: {starFill(star, trip.rating)}"></span>
              {/each}
            </span>
          {/if}
          {#if expenseTotals.length > 0}
            <div class="trip-card-expenses">
              {#each expenseTotals as label}
                <span class="trip-card-expense-pill">{label}</span>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      <!-- The stub's right-hand panel: where the trip stands, and the number
           that changes on its own. Kept out of the title row so a long trip
           name is never squeezed by a badge. -->
      <div class="trip-card-aside">
        {@render badge()}
        {#if footer}{@render footer()}{/if}
      </div>
    </div>
  </article>
</a>
