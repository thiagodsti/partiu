<script lang="ts">
  import { stationsApi, placesApi, citiesApi } from '../api/client';
  import type { PlaceResult, PlaceInputKind, PickedPlace } from '../api/types';
  import { t } from '../lib/i18n';

  interface Props {
    /** The place name. Bound both ways: typing edits it, picking a suggestion replaces it. */
    value: string;
    /** Coordinates of the picked place, or null when the name was typed by hand. */
    lat: number | null;
    lon: number | null;
    /** A station kind ('train' | 'bus' | 'ferry'), 'car', 'stay' or 'city'.
     * Selects both the endpoint and the OSM tags it filters on. 'car' and
     * 'city' both search settlements — a drive has no station — and both fall
     * back to plain addresses when the settlement pass comes back thin. */
    kind: PlaceInputKind;
    placeholder?: string;
    id?: string;
    /** Carries the geocoder's country code and street address alongside the
     * name — the country is what makes the leg count toward visited countries,
     * and the address is what makes the calendar entry tappable into maps. */
    onchange: (place: PickedPlace) => void;
  }

  const { value, lat, lon, kind, placeholder = '', id, onchange }: Props = $props();

  let results = $state<PlaceResult[]>([]);
  let open = $state(false);
  let searching = $state(false);
  let searchFailed = $state(false);
  let highlighted = $state(-1);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  /** Incremented per search so a slow response for an earlier query cannot
   * overwrite the results of a later one. */
  let requestSeq = 0;

  /** Per-component memo of queries already answered. Backspacing is the common
   * case — typing past a match and correcting it re-issues queries the server
   * has already answered, and the geocoder behind them is a rate-limited
   * third-party service. Lives for the life of the form, which is short enough
   * that staleness is not a concern. */
  const queryCache = new Map<string, PlaceResult[]>();

  /** The secondary line under a result: its street address where Photon had
   * one, since that is what distinguishes two results with the same name, and
   * city/country otherwise. */
  function label(s: PlaceResult): string {
    // A car's ends are cities too, so it reads the same way — but both pickers
    // can also return plain addresses, and those still want their address line.
    //
    // Photon's `address` for a city is the city itself ("Oslo" under "Oslo"),
    // which distinguishes nothing, while the one in Minnesota reads "Marshall" —
    // its county, with no hint of which country it is in. So a city shows region
    // + country, dropping the region when it merely repeats the name.
    if ((kind === 'city' || kind === 'car') && s.category === 'place') {
      const region = s.city && s.city !== s.name ? s.city : '';
      return [region, s.country].filter(Boolean).join(', ');
    }
    return s.address || [s.city, s.country].filter(Boolean).join(', ');
  }

  /** Venues before streets, so the "Addresses" heading is a single divider
   * rather than one per run. Photon interleaves the two by relevance, and the
   * heading repeated four times in a six-result list. `sort` is stable, so
   * relevance order is preserved inside each group. */
  const grouped = $derived(
    [...results].sort(
      (a, b) => (a.category === 'address' ? 1 : 0) - (b.category === 'address' ? 1 : 0),
    ),
  );

  /** The station wording is wrong on an accommodation form, where the thing
   * being picked is a hotel or a street. */
  const isStay = $derived(kind === 'stay');
  const isCity = $derived(kind === 'city');

  async function runSearch(q: string) {
    const seq = ++requestSeq;

    const memo = queryCache.get(q.toLowerCase());
    if (memo) {
      results = memo;
      open = memo.length > 0;
      searching = false;
      searchFailed = false;
      return;
    }

    searching = true;
    searchFailed = false;
    try {
      // Stays search accommodation *and* plain addresses; a private rental is
      // usually only findable as the latter. Stations stay tag-filtered.
      const found =
        kind === 'stay'
          ? await placesApi.search(q)
          : kind === 'city'
            ? await citiesApi.search(q)
            : await stationsApi.search(q, kind);
      if (seq !== requestSeq) return;
      queryCache.set(q.toLowerCase(), found);
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
    // Typing invalidates everything the geocoder resolved — the name no longer
    // necessarily refers to that place, so its coordinates, country and address
    // must go with it rather than being silently kept.
    onchange({ name: text, lat: null, lon: null, country_code: null, address: null });
    highlighted = -1;
    if (debounceTimer) clearTimeout(debounceTimer);
    if (text.trim().length < 3) {
      results = [];
      open = false;
      return;
    }
    debounceTimer = setTimeout(() => runSearch(text.trim()), 300);
  }

  function pick(s: PlaceResult) {
    onchange({
      name: s.name,
      lat: s.lat,
      lon: s.lon,
      country_code: s.countrycode || null,
      address: s.address || null,
    });
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
      <span class="station-spinner" aria-label={isStay || isCity ? $t('places.searching') : $t('segments.searching')}></span>
    {:else if lat != null && lon != null}
      <span class="station-pin" title={isStay || isCity ? $t('places.located') : $t('segments.located')}>📍</span>
    {/if}
  </span>

  {#if open && results.length > 0}
    <ul class="station-results">
      <!-- Keyed on the index, not the coordinate pair. These rows hold no state
           worth preserving across a re-render, and the coordinates come from a
           third-party geocoder that does repeat a point under two labels — a
           duplicate key is a hard error in Svelte, which took the whole page
           down behind the app's error boundary. The server collapses those
           repeats too; this is the half that cannot be re-broken from outside. -->
      {#each grouped as s, i (i)}
        {#if i > 0 && s.category === 'address' && grouped[i - 1].category !== 'address'}
          <li class="place-group">{$t('places.addresses')}</li>
        {/if}
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
    <p class="station-hint">
      {isStay || isCity ? $t('places.lookup_failed') : $t('segments.lookup_failed')}
    </p>
  {:else if value.trim() && lat == null}
    <p class="station-hint">
      {isCity ? $t('cities.no_coords_hint') : isStay ? $t('places.no_coords_hint') : $t('segments.no_coords_hint')}
    </p>
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

  .place-group {
    padding: 6px 9px 2px;
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted, #64748b);
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
