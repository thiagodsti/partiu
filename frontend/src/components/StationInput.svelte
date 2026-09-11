<script lang="ts">
  import { stationsApi } from '../api/client';
  import type { StationResult, SegmentType } from '../api/types';
  import { t } from '../lib/i18n';

  interface Props {
    /** The place name. Bound both ways: typing edits it, picking a suggestion replaces it. */
    value: string;
    /** Coordinates of the picked station, or null when the name was typed by hand. */
    lat: number | null;
    lon: number | null;
    kind: SegmentType;
    placeholder?: string;
    id?: string;
    onchange: (place: { name: string; lat: number | null; lon: number | null }) => void;
  }

  const { value, lat, lon, kind, placeholder = '', id, onchange }: Props = $props();

  let results = $state<StationResult[]>([]);
  let open = $state(false);
  let searching = $state(false);
  let searchFailed = $state(false);
  let highlighted = $state(-1);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  /** Incremented per search so a slow response for an earlier query cannot
   * overwrite the results of a later one. */
  let requestSeq = 0;

  function label(s: StationResult): string {
    return [s.city, s.country].filter(Boolean).join(', ');
  }

  async function runSearch(q: string) {
    const seq = ++requestSeq;
    searching = true;
    searchFailed = false;
    try {
      const found = await stationsApi.search(q, kind);
      if (seq !== requestSeq) return;
      results = found;
      open = found.length > 0;
    } catch {
      if (seq !== requestSeq) return;
      // The geocoder is optional: leave whatever the user typed in place and
      // let them save it as a plain label rather than blocking the form.
      results = [];
      searchFailed = true;
      open = false;
    } finally {
      if (seq === requestSeq) searching = false;
    }
  }

  function onInput(e: Event) {
    const text = (e.target as HTMLInputElement).value;
    // Typing invalidates any previously picked station's coordinates — the name
    // no longer necessarily refers to that place.
    onchange({ name: text, lat: null, lon: null });
    highlighted = -1;
    if (debounceTimer) clearTimeout(debounceTimer);
    if (text.trim().length < 3) {
      results = [];
      open = false;
      return;
    }
    debounceTimer = setTimeout(() => runSearch(text.trim()), 300);
  }

  function pick(s: StationResult) {
    onchange({ name: s.name, lat: s.lat, lon: s.lon });
    results = [];
    open = false;
    highlighted = -1;
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open || results.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      highlighted = (highlighted + 1) % results.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      highlighted = highlighted <= 0 ? results.length - 1 : highlighted - 1;
    } else if (e.key === 'Enter' && highlighted >= 0) {
      e.preventDefault();
      pick(results[highlighted]);
    } else if (e.key === 'Escape') {
      open = false;
      highlighted = -1;
    }
  }
</script>

<div class="station-input">
  <input
    {id}
    class="form-input"
    type="text"
    autocomplete="off"
    {placeholder}
    {value}
    oninput={onInput}
    onkeydown={onKeydown}
    onfocus={() => { if (results.length > 0) open = true; }}
    onblur={() => setTimeout(() => (open = false), 150)}
  />

  <span class="station-status">
    {#if searching}
      <span class="station-spinner" aria-label={$t('segments.searching')}></span>
    {:else if lat != null && lon != null}
      <span class="station-pin" title={$t('segments.located')}>📍</span>
    {/if}
  </span>

  {#if open && results.length > 0}
    <ul class="station-results">
      {#each results as s, i (`${s.lat},${s.lon}`)}
        <li>
          <button
            type="button"
            class="station-result"
            class:highlighted={i === highlighted}
            onmousedown={(e) => { e.preventDefault(); pick(s); }}
            onmouseenter={() => (highlighted = i)}
          >
            <span class="station-name">{s.name}</span>
            {#if label(s)}<span class="station-where">{label(s)}</span>{/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if searchFailed}
    <p class="station-hint">{$t('segments.lookup_failed')}</p>
  {:else if value.trim() && lat == null}
    <p class="station-hint">{$t('segments.no_coords_hint')}</p>
  {/if}
</div>

<style>
  .station-input {
    position: relative;
  }

  .station-status {
    position: absolute;
    right: 8px;
    top: 9px;
    font-size: 0.8rem;
    pointer-events: none;
  }

  .station-spinner {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid var(--border, #ddd);
    border-top-color: var(--accent, #3b82f6);
    border-radius: 50%;
    animation: station-spin 0.7s linear infinite;
  }

  @keyframes station-spin {
    to { transform: rotate(360deg); }
  }

  .station-results {
    position: absolute;
    z-index: 30;
    top: calc(100% + 2px);
    left: 0;
    right: 0;
    margin: 0;
    padding: 4px;
    list-style: none;
    max-height: 240px;
    overflow-y: auto;
    background: var(--surface, #fff);
    border: 1px solid var(--border, #e2e8f0);
    border-radius: var(--radius-md, 8px);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
  }

  .station-result {
    display: flex;
    flex-direction: column;
    gap: 1px;
    width: 100%;
    padding: 7px 9px;
    border: 0;
    border-radius: var(--radius-sm, 6px);
    background: none;
    text-align: left;
    cursor: pointer;
    color: var(--text, inherit);
  }

  .station-result.highlighted {
    background: var(--surface-hover, rgba(59, 130, 246, 0.1));
  }

  .station-name {
    font-size: 0.88rem;
    font-weight: 500;
  }

  .station-where {
    font-size: 0.76rem;
    color: var(--text-muted, #64748b);
  }

  .station-hint {
    margin: 3px 0 0;
    font-size: 0.72rem;
    color: var(--text-muted, #64748b);
  }
</style>
