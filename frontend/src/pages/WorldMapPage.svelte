<script lang="ts">
  import { onMount } from 'svelte';
  import worldMap from '@svg-maps/world';
  import { statsApi } from '../api/client';
  import { t } from '../lib/i18n';

  let visitedSet = $state<Set<string>>(new Set());
  let loading = $state(true);
  let tooltip = $state<{ name: string; x: number; y: number } | null>(null);
  let tappedCountry = $state<string | null>(null);
  let yearLabel = $state<number | null>(null);

  onMount(async () => {
    try {
      // Read year directly from the hash (e.g. #/stats/map?year=2020)
      const hash = window.location.hash;
      const qmark = hash.indexOf('?');
      const qs = qmark >= 0 ? hash.slice(qmark + 1) : '';
      const yearStr = new URLSearchParams(qs).get('year');
      const year = yearStr ? Number(yearStr) : undefined;
      yearLabel = year ?? null;

      const stats = await statsApi.get(year);
      visitedSet = new Set(stats.visited_countries.map((c) => c.toLowerCase()));
    } finally {
      loading = false;
    }
  });

  function onMouseEnter(e: MouseEvent, name: string) {
    tooltip = { name, x: e.clientX, y: e.clientY };
  }

  function onMouseMove(e: MouseEvent, name: string) {
    tooltip = { name, x: e.clientX, y: e.clientY };
  }

  function onMouseLeave() {
    tooltip = null;
  }

  function onTap(name: string) {
    tappedCountry = tappedCountry === name ? null : name;
  }
</script>

<div class="map-page">
  <div class="map-header">
    <a href="#/stats" class="btn btn-secondary btn-sm back-btn">← {$t('flight.back')}</a>
    <h2 class="map-title">{$t('stats.countries_visited')}{yearLabel ? ` · ${yearLabel}` : ''}</h2>
    <span class="map-count">{visitedSet.size}</span>
  </div>

  {#if loading}
    <div class="map-loading">{$t('stats.loading')}</div>
  {:else}
    <div class="map-wrap">
      <svg
        viewBox={worldMap.viewBox}
        class="world-svg"
        aria-label={$t('stats.countries_visited')}
      >
        {#each worldMap.locations as loc}
          {@const visited = visitedSet.has(loc.id)}
          <path
            d={loc.path}
            class="country"
            class:visited
            aria-label={loc.name}
            onmouseenter={(e) => onMouseEnter(e, loc.name)}
            onmousemove={(e) => onMouseMove(e, loc.name)}
            onmouseleave={onMouseLeave}
            ontouchend={() => onTap(loc.name)}
            role="img"
          />
        {/each}
      </svg>
    </div>

    {#if tappedCountry}
      <div class="tapped-label">{tappedCountry}</div>
    {/if}

    <div class="country-list">
      {#each [...visitedSet].sort() as code}
        {@const loc = worldMap.locations.find((l: { id: string; name: string }) => l.id === code)}
        {#if loc}
          <span class="country-chip">{loc.name}</span>
        {/if}
      {/each}
    </div>
  {/if}
</div>

{#if tooltip}
  <div class="map-tooltip" style="left:{tooltip.x + 12}px; top:{tooltip.y - 8}px">
    {tooltip.name}
    {#if visitedSet.has(worldMap.locations.find((l: { id: string; name: string }) => l.name === tooltip?.name)?.id ?? '')}
      <span class="tooltip-visited">✓</span>
    {/if}
  </div>
{/if}

<style>
  .map-page {
    display: flex;
    flex-direction: column;
    min-height: 100dvh;
    background: var(--bg-primary);
  }

  .map-header {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    padding: var(--space-md);
    border-bottom: 1px solid var(--border);
  }

  .map-title {
    font-size: 1.1rem;
    font-weight: 600;
    flex: 1;
    margin: 0;
  }

  .map-count {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    padding: 2px 10px;
    border-radius: 999px;
  }

  .map-wrap {
    width: 100%;
    padding: var(--space-md);
    box-sizing: border-box;
    background: var(--bg-secondary);
    border-radius: var(--radius-md);
    margin: 0 var(--space-md);
    width: calc(100% - var(--space-md) * 2);
  }

  .world-svg {
    width: 100%;
    height: auto;
    display: block;
  }

  .country {
    fill: var(--text-muted);
    stroke: var(--bg-primary);
    stroke-width: 0.5;
    cursor: pointer;
    transition: fill 0.15s;
    opacity: 0.5;
  }

  .country.visited {
    fill: var(--accent);
    opacity: 1;
  }

  @media (hover: hover) {
    .country:hover {
      opacity: 0.75;
    }

    .country.visited:hover {
      fill: var(--accent-hover);
      opacity: 1;
    }
  }

  .tapped-label {
    text-align: center;
    font-size: 0.95rem;
    font-weight: 500;
    color: var(--text-primary);
    padding: 0 var(--space-md) var(--space-sm);
  }

  .map-loading {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
  }

  .country-list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md) var(--space-xl);
  }

  .country-chip {
    font-size: 0.8rem;
    padding: 2px 10px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
    border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  }

  .map-tooltip {
    position: fixed;
    pointer-events: none;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 4px 10px;
    font-size: 0.85rem;
    color: var(--text-primary);
    z-index: 100;
    white-space: nowrap;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  }

  .tooltip-visited {
    color: var(--accent);
    margin-left: 4px;
    font-weight: 700;
  }
</style>
