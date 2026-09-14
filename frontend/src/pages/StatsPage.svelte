<script lang="ts">
  import { statsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import MonthlyChart from '../components/MonthlyChart.svelte';
  import { t, locale } from '../lib/i18n';

  type Stats = Awaited<ReturnType<typeof statsApi.get>>;

  let stats = $state<Stats | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let selectedYear = $state<number | null>(null);

  async function load(year?: number) {
    loading = true;
    error = null;
    try {
      stats = await statsApi.get(year);
      // On first load, if years are available and none selected, show all-time
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  function selectYear(y: number | null) {
    selectedYear = y;
    load(y ?? undefined);
  }

  /** Country codes rendered as names for the hero subtitle ("Sweden · Norway").
   * `Intl.DisplayNames` is built in and locale-aware, so no lookup table is
   * needed; a code it cannot resolve falls back to itself rather than
   * disappearing. Capped so a well-travelled year does not wrap the hero. */
  const HERO_COUNTRY_LIMIT = 6;

  const countryNames = $derived.by((): string => {
    const codes = stats?.visited_countries ?? [];
    if (codes.length === 0) return '';
    let display: Intl.DisplayNames | null = null;
    try {
      display = new Intl.DisplayNames([$locale ?? 'en'], { type: 'region' });
    } catch {
      display = null;
    }
    const names = codes
      .slice(0, HERO_COUNTRY_LIMIT)
      .map((c) => {
        try {
          return display?.of(c) ?? c;
        } catch {
          return c;
        }
      })
      .join(' · ');
    return codes.length > HERO_COUNTRY_LIMIT
      ? `${names} +${codes.length - HERO_COUNTRY_LIMIT}`
      : names;
  });

  function fmtKm(km: number): string {
    if (km >= 1_000_000) return `${(km / 1_000_000).toFixed(1)}M`;
    if (km >= 10_000) return `${Math.round(km / 1_000)}k`;
    return km.toLocaleString();
  }

  function fmtHours(h: number): string {
    const days = Math.floor(h / 24);
    const rem = Math.round(h % 24);
    if (days > 0) return `${days}d ${rem}h`;
    return `${h}h`;
  }

  const airlineNames: Record<string, string> = {
    LA: 'LATAM', SK: 'SAS', DY: 'Norwegian', LH: 'Lufthansa',
    AD: 'Azul', AA: 'American', UA: 'United', DL: 'Delta',
    BA: 'British Airways', AF: 'Air France', KL: 'KLM',
    IB: 'Iberia', EK: 'Emirates', QR: 'Qatar', TK: 'Turkish',
    FR: 'Ryanair', U2: 'easyJet', W6: 'Wizz Air', G3: 'GOL',
  };

  function airlineName(code: string, label: string | null) {
    return label ?? airlineNames[code] ?? code;
  }

  function fmtCo2(kg: number): string {
    if (kg >= 1000) return $t('stats.co2_tonnes', { values: { n: (kg / 1000).toFixed(1) } });
    return $t('stats.co2_kg', { values: { n: Math.round(kg) } });
  }
</script>

<TopNav title={$t('nav.stats')} />

<div class="main-content stats-page">
  {#if loading}
    <LoadingScreen message={$t('stats.loading')} />
  {:else if error}
    <div class="stats-error">⚠ {error}</div>
  {:else if stats}

    <!-- Year pills -->
    {#if stats.years.length > 1}
      <div class="year-pills">
        <button
          class="year-pill"
          class:active={selectedYear === null}
          onclick={() => selectYear(null)}
        >{$t('stats.all_time')}</button>
        {#each stats.years as y}
          <button
            class="year-pill"
            class:active={selectedYear === Number(y)}
            onclick={() => selectYear(Number(y))}
          >{y}</button>
        {/each}
      </div>
    {/if}

    <!-- A trip made entirely of trains has no flights but real countries, so
         the empty state keys off "nothing at all" rather than the flight count.
         The hero and the flight-shaped cards below still read zero, which is
         honest — ground travel deliberately contributes only countries. -->
    {#if stats.total_flights === 0 && stats.unique_countries === 0}
      <div class="stats-empty">
        <div class="stats-empty-icon">✈</div>
        <p>{$t('stats.empty')}</p>
      </div>
    {:else}

      <!-- Hero. Distance is the headline for anyone who flies, but it reads
           "0 km" for a period spent entirely on trains, so countries take over
           when there are no flights. Ground travel has no distance of its own
           on purpose: rail track runs well above the great-circle line, and an
           estimate rendered this large would read as a measurement. -->
      {#if stats.total_flights === 0}
        <div class="stat-hero">
          <div class="stat-hero-number">{stats.unique_countries}</div>
          <div class="stat-hero-label">{$t('stats.countries_visited')}</div>
          {#if countryNames}
            <div class="stat-hero-sub">{countryNames}</div>
          {/if}
        </div>
      {:else}
        <div class="stat-hero">
          <div class="stat-hero-number">{fmtKm(stats.total_km)} <span class="stat-hero-unit">km</span></div>
          <div class="stat-hero-label">{$t('stats.total_distance')}</div>
          {#if stats.earth_laps > 0}
            <div class="stat-hero-sub">
              {#if stats.earth_laps >= 1}
                {$t('stats.earth_laps', { values: { n: stats.earth_laps.toFixed(1) } })}
              {:else}
                {$t('stats.earth_pct', { values: { pct: Math.round(stats.earth_laps * 100) } })}
              {/if}
            </div>
          {/if}
        </div>
      {/if}

      <!-- 4-up stat grid -->
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-value">{stats.total_flights}</div>
          <div class="stat-label">{$t('stats.flights')}</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{fmtHours(stats.total_hours)}</div>
          <div class="stat-label">{$t('stats.airtime')}</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{stats.unique_airports}</div>
          <div class="stat-label">{$t('stats.airports')}</div>
        </div>
        <a class="stat-card stat-card-link" href="#/stats/map{selectedYear ? `?year=${selectedYear}` : ''}">
          <div class="stat-value">{stats.unique_countries}</div>
          <div class="stat-label">{$t('stats.countries')}</div>
        </a>
        {#if stats.ground_legs > 0}
          <div class="stat-card">
            <div class="stat-value">{stats.ground_legs}</div>
            <div class="stat-label">{$t('stats.ground_legs')}</div>
          </div>
        {/if}
        {#if stats.nights_away > 0}
          <div class="stat-card">
            <div class="stat-value">{stats.nights_away}</div>
            <div class="stat-label">{$t('stats.nights_away')}</div>
          </div>
        {/if}
        {#if stats.total_co2_kg > 0}
          <div class="stat-card stat-card-co2">
            <div class="stat-value">{fmtCo2(stats.total_co2_kg)}</div>
            <div class="stat-label">{$t('stats.co2')}</div>
          </div>
        {/if}
      </div>

      <!-- Flights over time chart -->
      {#if stats.flights_by_period && stats.flights_by_period.some((p) => p.count > 0)}
        <div class="stat-section">
          <div class="stat-section-title">{$t('stats.flights_over_time')}</div>
          <MonthlyChart data={stats.flights_by_period} />
        </div>
      {/if}

      <!-- Longest flight -->
      {#if stats.longest_flight_km > 0}
        <div class="stat-section">
          <div class="stat-section-title">{$t('stats.longest_flight')}</div>
          <div class="stat-highlight-card">
            <span class="route-tag">{stats.longest_flight_route.replace('→', ' → ')}</span>
            <span class="route-km">{stats.longest_flight_km.toLocaleString()} km</span>
          </div>
        </div>
      {/if}

      <!-- Top routes -->
      {#if stats.top_routes.length > 0}
        <div class="stat-section">
          <div class="stat-section-title">{$t('stats.top_routes')}</div>
          <div class="stat-list">
            {#each stats.top_routes as r, i}
              <div class="stat-list-item">
                <span class="stat-rank">{i + 1}</span>
                <span class="stat-list-label route-mono">{r.key.replace('→', ' → ')}</span>
                <span class="stat-list-count">{r.count}×</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Top airports -->
      {#if stats.top_airports.length > 0}
        <div class="stat-section">
          <div class="stat-section-title">{$t('stats.top_airports')}</div>
          <div class="stat-list">
            {#each stats.top_airports as a, i}
              <div class="stat-list-item">
                <span class="stat-rank">{i + 1}</span>
                <span class="stat-list-label route-mono">{a.key}</span>
                <div class="stat-bar-wrap">
                  <div
                    class="stat-bar"
                    style="width:{Math.round((a.count / stats.top_airports[0].count) * 100)}%"
                  ></div>
                </div>
                <span class="stat-list-count">{a.count}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Distance breakdown -->
      {#if stats.flight_breakdown && stats.flight_breakdown.length > 0}
        <div class="stat-section">
          <div class="stat-section-title">{$t('stats.distance_breakdown')}</div>
          <div class="stat-list breakdown-list">
            <div class="breakdown-scroll">
              {#each stats.flight_breakdown as f}
                <div class="stat-list-item">
                  <div class="breakdown-main">
                    <span class="stat-list-label route-mono">{f.route.replace('→', ' → ')}</span>
                    {#if f.trip_name}<span class="breakdown-trip">{f.trip_name}</span>{/if}
                  </div>
                  {#if f.flight}<span class="breakdown-flight">{f.flight}</span>{/if}
                  <div class="breakdown-numbers">
                    <span class="stat-list-count">{f.km > 0 ? f.km.toLocaleString() + ' km' : '—'}</span>
                    {#if f.co2_kg > 0}<span class="breakdown-co2">{fmtCo2(f.co2_kg)}</span>{/if}
                  </div>
                </div>
              {/each}
            </div>
            <div class="stat-list-item breakdown-total">
              <span class="stat-list-label">{$t('stats.total')}</span>
              <div class="breakdown-numbers">
                <span class="stat-list-count">{stats.total_km.toLocaleString()} km</span>
                {#if stats.total_co2_kg > 0}<span class="breakdown-co2">{fmtCo2(stats.total_co2_kg)}</span>{/if}
              </div>
            </div>
          </div>
        </div>
      {/if}

      <!-- Airlines -->
      {#if stats.top_airlines.length > 0}
        <div class="stat-section">
          <div class="stat-section-title">{$t('stats.airlines')}</div>
          <div class="airline-chips">
            {#each stats.top_airlines as a}
              <div class="airline-chip airline-{a.key}">
                <span class="airline-chip-code">{a.key}</span>
                <span class="airline-chip-name">{airlineName(a.key, a.label)}</span>
                <span class="airline-chip-count">{a.count}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Export -->
      <div class="stat-section">
        <a class="export-link" href="/api/flights/export.csv" download="flights.csv">
          ↓ {$t('stats.export_csv')}
        </a>
      </div>

    {/if}
  {/if}
</div>

<style>
  /* The shell already clears the dock; the page only needs its own rhythm. */
  .stats-page {
    display: flex;
    flex-direction: column;
    gap: var(--space-lg);
  }

  /* ---- Year pills ---- */
  .year-pills {
    display: flex;
    gap: var(--space-xs);
    flex-wrap: wrap;
  }

  .year-pill {
    padding: 4px 14px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.8rem;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .year-pill.active,
  .year-pill:hover {
    background: var(--accent);
    color: var(--accent-on);
    border-color: var(--accent);
    font-weight: 600;
  }

  /* ---- Hero ---- */
  /* One flat amber field with the number set in condensed ink — the same
     black-on-yellow the primary button uses, at the size a gate sign uses it.
     The gradient it replaces ran amber into violet, a colour that appears
     nowhere else in the app and meant nothing where it did appear. */
  .stat-hero {
    padding: var(--space-lg);
    background: var(--accent);
    border-radius: var(--radius-lg);
    color: var(--accent-on);
  }

  .stat-hero-number {
    font-family: var(--font-display);
    font-size: clamp(3.4rem, 11vw, 6rem);
    font-weight: 700;
    line-height: 0.92;
    letter-spacing: 0.005em;
  }

  .stat-hero-unit {
    font-size: 0.38em;
    font-weight: 600;
    margin-left: 0.15em;
  }

  .stat-hero-label {
    margin-top: var(--space-sm);
    font-size: 1.05rem;
    font-weight: 600;
  }

  .stat-hero-sub {
    margin-top: 2px;
    font-size: 0.88rem;
    opacity: 0.72;
  }

  /* ---- stat grid ---- */
  /* Hairline-separated cells of one board rather than free-floating tiles,
     so the numbers line up down the page and can be compared. */
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .stat-card {
    background: var(--bg-card);
    padding: var(--space-md);
  }

  .stat-card-link {
    text-decoration: none;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }

  @media (hover: hover) {
    .stat-card-link:hover {
      background: color-mix(in srgb, var(--accent) 10%, var(--bg-card));
    }
  }

  .stat-value {
    font-family: var(--font-display);
    font-size: 2.2rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1;
  }

  .stat-label {
    margin-top: 2px;
    font-size: 0.82rem;
    color: var(--text-muted);
  }

  .stat-card-link .stat-label::after {
    content: ' ↗';
    color: var(--accent-text);
  }

  /* ---- Sections ---- */
  .stat-section-title {
    font-family: var(--font-display);
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    color: var(--text-primary);
    margin-bottom: var(--space-sm);
  }

  /* ---- Highlight card (longest flight) ---- */
  .stat-highlight-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-md);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-sm);
  }

  .route-tag {
    font-family: var(--font-mono);
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .route-km {
    font-size: 0.9rem;
    color: var(--accent-text);
    font-weight: 600;
    white-space: nowrap;
  }

  /* ---- List rows ---- */
  .breakdown-scroll {
    max-height: 320px;
    overflow-y: auto;
  }

  .breakdown-list .breakdown-total {
    border-top: 2px solid var(--border);
  }

  .stat-list {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .stat-list-item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: 10px var(--space-md);
    border-bottom: 1px solid var(--border-light);
  }

  .stat-list-item:last-child {
    border-bottom: none;
  }

  .stat-rank {
    width: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--text-muted);
    text-align: center;
    flex-shrink: 0;
  }

  .stat-list-label {
    flex: 1;
    font-size: 0.9rem;
    color: var(--text-primary);
  }

  .route-mono {
    font-family: var(--font-mono);
  }

  .stat-bar-wrap {
    width: 60px;
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    flex-shrink: 0;
  }

  .stat-bar {
    height: 100%;
    background: var(--accent);
    border-radius: 2px;
    min-width: 4px;
    transition: width 0.4s ease;
  }

  .stat-list-count {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-muted);
    min-width: 28px;
    text-align: right;
    flex-shrink: 0;
  }

  /* ---- Airline chips ---- */
  .airline-chips {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .airline-chip {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: 10px var(--space-md);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }

  .airline-chip-code {
    font-family: var(--font-mono);
    font-weight: 700;
    font-size: 0.9rem;
    width: 28px;
  }

  .airline-chip-name {
    flex: 1;
    font-size: 0.9rem;
    color: var(--text-primary);
  }

  .airline-chip-count {
    font-size: 0.8rem;
    color: var(--text-muted);
    font-weight: 600;
  }

  /* ---- Breakdown ---- */
  .breakdown-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }

  .breakdown-trip {
    font-size: 0.7rem;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .breakdown-flight {
    font-size: 0.75rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
    flex-shrink: 0;
  }

  .breakdown-numbers {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 1px;
    flex-shrink: 0;
  }

  .breakdown-co2 {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-weight: 400;
  }

  .breakdown-total {
    font-weight: 600;
  }


  .export-link {
    display: inline-block;
    font-size: 0.8125rem;
    color: var(--text-muted);
    text-decoration: none;
    padding: 0.4rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    transition: color 0.15s, border-color 0.15s;
  }

  .export-link:hover {
    color: var(--text-primary);
    border-color: var(--accent);
  }

  .breakdown-total .stat-list-label {
    font-weight: 600;
    color: var(--text-primary);
  }

  .breakdown-total .stat-list-count {
    color: var(--accent-text);
    font-weight: 700;
  }

  /* ---- Empty / error ---- */
  .stats-empty {
    text-align: center;
    padding: var(--space-xl) var(--space-md);
    color: var(--text-muted);
  }

  .stats-empty-icon {
    font-size: 3rem;
    margin-bottom: var(--space-md);
  }

  .stats-error {
    padding: var(--space-md);
    color: var(--danger-text);
    text-align: center;
  }
</style>
