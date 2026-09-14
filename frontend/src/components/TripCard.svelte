<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Trip } from "../api/types";
  import { budgetLevel, formatCurrencyTotals, formatDateRange } from "../lib/utils";
  import { t } from "../lib/i18n";

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
    showStars?: boolean;
    /** Drives the edge stripe's colour; the badge snippet still supplies the words. */
    status?: "upcoming" | "ongoing" | "completed";
    onImageError: (e: Event) => void;
    badge: Snippet;
    footer?: Snippet;
  }

  const {
    trip,
    href,
    imageUrl,
    imgFailed,
    showStars = false,
    status = "upcoming",
    onImageError,
    badge,
    footer,
  }: Props = $props();

  const dateRange = $derived(formatDateRange(trip.start_date, trip.end_date));
  const flightCount = $derived(trip.flight_count ?? 0);
  const segmentCount = $derived(trip.segment_count ?? 0);
  const stayCount = $derived(trip.stay_count ?? 0);
  const segmentTypes = $derived(trip.segment_types ?? []);

  const SEGMENT_ICONS: Record<string, string> = {
    train: "🚆",
    bus: "🚌",
    ferry: "⛴️",
    car: "🚗",
  };

  /** Fixed glyph order for a mixed trip, so the chip reads the same every time
   *  rather than following whatever order the rows came back in. */
  const SEGMENT_ORDER = ["train", "bus", "ferry", "car"];

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
      parts.push(`✈ ${plural("trips.flight_count", flightCount)}`);
    }
    if (segmentCount > 0) {
      /* A trip of one kind names that kind ("2 drives"); a mixed one falls back
       * to the generic "3 legs", because no single word covers ferry-and-car.
       *
       * The **icon** has to keep the same promise. It used to default to the
       * train glyph whenever the types were mixed — or unknown — so a ferry and
       * two drives showed up as "🚆 3 legs", claiming a train the trip never
       * took. A mixed trip now shows one glyph per kind it actually contains,
       * in a fixed order so the chip does not reshuffle between renders. */
      const kinds = SEGMENT_ORDER.filter((type) => segmentTypes.includes(type));
      const onlyType = kinds.length === 1 && segmentTypes.length === 1 ? kinds[0] : null;
      // Neutral when the types are unrecognised: a glyph we cannot map is not a
      // train either, and guessing is what this whole branch exists to avoid.
      const icon = kinds.length ? kinds.map((type) => SEGMENT_ICONS[type]).join("") : "↔";
      const label = onlyType
        ? plural(`trips.segment_count_${onlyType}`, segmentCount)
        : plural("trips.segment_count", segmentCount);
      parts.push(`${icon} ${label}`);
    }
    if (stayCount > 0) {
      parts.push(`🛏 ${plural("trips.stay_count", stayCount)}`);
    }
    return parts;
  });
  const refs = $derived((trip.booking_refs ?? []).join(", "));
  const showStarRow = $derived(showStars || !!trip.rating);

  /**
   * The routing line a bag tag prints.
   *
   * The **typed** ends win over the flight-derived airport codes: they are the
   * only ones a person chose, and they are all a trip that is driven or ridden
   * has — the airport pair is empty for those, since `_recompute_span` fills it
   * from the flights alone. Each end falls back independently, so a trip flown
   * out and driven back still prints both.
   *
   * Only shown when the two ends differ: `_recompute_span` sets destination to
   * the *final* arrival, so a round trip has origin === destination and
   * "GRU → GRU" would be noise.
   */
  const from = $derived(trip.origin_place || trip.origin_airport || null);
  const listed = $derived(trip.destinations ?? []);
  const to = $derived(listed[0]?.name || trip.destination_airport || null);
  /* A multi-stop trip prints its first destination and a count. The bag-tag
   * line stays one line high whatever the trip does; the full list lives on
   * the trip page, which is where you go when you want it. */
  const extra = $derived(Math.max(0, listed.length - 1));
  const routing = $derived(
    from && to && from !== to ? `${from} → ${to}${extra ? ` +${extra}` : ''}` : from,
  );

  const expenseTotals = $derived(formatCurrencyTotals(trip.expenses_total));

  /* The budget, but **only when it needs attention**. A card is a glance, and
   * what an overview is for is spotting the one trip that wants looking at —
   * the figures and the bar belong on the page you opened deliberately. Same
   * reasoning as the status badge, which shows no dot for `upcoming` because
   * nothing has happened yet.
   *
   * Note there is no check on whether the trip has started: a trip still weeks
   * away has already bought its flights and booked its hotels, and that money
   * is spent. */
  const budgetAlarm = $derived.by(() => {
    const level = budgetLevel(trip.budget_spent ?? 0, trip.budget_amount);
    if (level !== 'near' && level !== 'over') return null;
    const currency = trip.budget_currency;
    if (!currency) return null;
    return {
      level,
      label: `${formatCurrencyTotals({ [currency]: trip.budget_spent ?? 0 })[0]} / ${
        formatCurrencyTotals({ [currency]: trip.budget_amount! })[0]
      }`,
    };
  });

  function starFill(
    star: number,
    rating: number | null | undefined,
  ): "100%" | "50%" | "0%" {
    const r = rating ?? 0;
    if (r >= star) return "100%";
    if (r >= star - 0.5) return "50%";
    return "0%";
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
            <span class="text-sm text-muted"
              >{$t("trips.ref", { values: { refs } })}</span
            >
          {/if}
          {#if showStarRow}
            <span class="trip-card-stars" aria-label={$t("trips.rating_label")}>
              {#each [1, 2, 3, 4, 5] as star}
                <span
                  class="star-display"
                  style="--fill: {starFill(star, trip.rating)}"
                ></span>
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
          {#if budgetAlarm}
            <!-- Only when it needs attention; a budget with room left says
                 nothing a card has space for. -->
            <p class="trip-card-budget" data-level={budgetAlarm.level}>
              🎯 {budgetAlarm.label}
            </p>
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
