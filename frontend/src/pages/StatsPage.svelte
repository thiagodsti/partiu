<script lang="ts">
  import { statsApi } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import { t } from '../lib/i18n';

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

  function airlineName(code: string) {
    return airlineNames[code] ?? code;
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

    {#if stats.total_flights === 0}
      <div class="stats-empty">
        <div class="stats-empty-icon">✈</div>
        <p>{$t('stats.empty')}</p>
      </div>
    {:else}

      <!-- Hero: km flown -->
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
          <div class="stat-label">{$t('stats.countries')} →</div>
        </a>
      </div>

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
                  <span class="stat-list-count">{f.km > 0 ? f.km.toLocaleString() + ' km' : '—'}</span>
                </div>
              {/each}
            </div>
            <div class="stat-list-item breakdown-total">
              <span class="stat-list-label">{$t('stats.total')}</span>
              <span class="stat-list-count">{stats.total_km.toLocaleString()} km</span>
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
                <span class="airline-chip-name">{airlineName(a.key)}</span>
                <span class="airline-chip-count">{a.count}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

    {/if}
  {/if}
</div>

<style>
  .stats-page {
    padding-bottom: calc(var(--tab-height) + var(--space-xl));
  }

  /* ---- Year pills ---- */
  .year-pills {
    display: flex;
    gap: var(--space-xs);
    flex-wrap: wrap;
    padding: var(--space-md) var(--space-md) 0;
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
    color: #fff;
    border-color: var(--accent);
  }

  /* ---- Hero ---- */
  .stat-hero {
    margin: var(--space-lg) var(--space-md) var(--space-md);
    padding: var(--space-xl) var(--space-md);
    background: linear-gradient(135deg, var(--accent) 0%, #8b5cf6 100%);
    border-radius: var(--radius-lg);
    text-align: center;
    color: #fff;
  }

  .stat-hero-number {
    font-size: clamp(2.8rem, 12vw, 4.5rem);
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.02em;
  }

  .stat-hero-unit {
    font-size: 0.5em;
    font-weight: 500;
    opacity: 0.85;
  }

  .stat-hero-label {
    margin-top: var(--space-xs);
    font-size: 1rem;
    opacity: 0.9;
    font-weight: 500;
  }

  .stat-hero-sub {
    margin-top: var(--space-xs);
    font-size: 0.85rem;
    opacity: 0.75;
  }

  /* ---- 4-up grid ---- */
  .stat-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-sm);
    padding: 0 var(--space-md);
  }

  .stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-md);
    text-align: center;
  }

  .stat-card-link {
    text-decoration: none;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }

  @media (hover: hover) {
    .stat-card-link:hover {
      border-color: var(--accent);
      background: color-mix(in srgb, var(--accent) 6%, var(--bg-card));
    }
  }

  .stat-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.1;
  }

  .stat-label {
    margin-top: 4px;
    font-size: 0.75rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  /* ---- Sections ---- */
  .stat-section {
    margin: var(--space-md) var(--space-md) 0;
  }

  .stat-section-title {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted);
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
    font-family: monospace;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .route-km {
    font-size: 0.9rem;
    color: var(--accent);
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
    font-family: monospace;
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
    font-family: monospace;
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
    font-family: monospace;
    flex-shrink: 0;
  }

  .breakdown-total {
    font-weight: 600;
  }

  .breakdown-total .stat-list-label {
    font-weight: 600;
    color: var(--text-primary);
  }

  .breakdown-total .stat-list-count {
    color: var(--accent);
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
    color: var(--danger);
    text-align: center;
  }
</style>
