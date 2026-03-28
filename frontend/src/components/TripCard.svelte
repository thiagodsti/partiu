<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Trip } from '../api/types';
  import { formatDateRange } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    trip: Trip;
    href: string;
    imageUrl: string;
    imgFailed: boolean;
    refreshing: boolean;
    showStars?: boolean;
    onImageError: (e: Event) => void;
    onRefreshImage: (e: MouseEvent) => void;
    badge: Snippet;
    footer?: Snippet;
  }

  const { trip, href, imageUrl, imgFailed, refreshing, showStars = false, onImageError, onRefreshImage, badge, footer }: Props = $props();

  const dateRange = $derived(formatDateRange(trip.start_date, trip.end_date));
  const flightCount = $derived(trip.flight_count ?? 0);
  const refs = $derived((trip.booking_refs ?? []).join(', '));
  const showStarRow = $derived(showStars || !!trip.rating);

  function starFill(star: number, rating: number | null | undefined): '100%' | '50%' | '0%' {
    const r = rating ?? 0;
    if (r >= star) return '100%';
    if (r >= star - 0.5) return '50%';
    return '0%';
  }
</script>

<a class="card-link" {href}>
  <article class="card trip-card">
    <div class="trip-card-cover" class:no-image={imgFailed}>
      {#if imgFailed}
        <span class="trip-card-no-image-icon">✈</span>
      {:else}
        <img
          src={imageUrl}
          alt=""
          class="trip-card-cover-img"
          onerror={onImageError}
        />
      {/if}
      <button
        class="trip-card-img-refresh"
        title="Find a different image"
        disabled={refreshing}
        onclick={onRefreshImage}
      >
        {refreshing ? '…' : '↻'}
      </button>
    </div>
    <div class="trip-card-header">
      <h2 class="trip-card-title">{trip.name}</h2>
      {@render badge()}
    </div>
    {#if dateRange}
      <div class="trip-card-meta">
        <span>📅 {dateRange}</span>
        <span>✈ {flightCount !== 1
          ? $t('trips.flight_count_plural', { values: { n: flightCount } })
          : $t('trips.flight_count', { values: { n: flightCount } })}</span>
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
      {#if footer}{@render footer()}{/if}
    </div>
  </article>
</a>
