<script lang="ts" module>
  import type { SuggestInterest, Suggestion } from '../api/types';

  /** What the panel last showed for one stop or day, kept for the rest of the
   * visit: closing it by mistake must not cost another request. */
  interface Memory {
    picked: SuggestInterest[];
    wish: string;
    results: Suggestion[];
    city: string;
    stay: { name: string; lat: number; lon: number } | null;
    stayWithoutPin: string | null;
    added: string[];
    unpinned: string[];
  }
  const memory = new Map<string, Memory>();

  /** For tests. */
  export function forgetSuggestions() {
    memory.clear();
  }
</script>

<script lang="ts">
  /**
   * "Suggest ideas" for a route city or a day of the planner.
   *
   * The traveller picks a few interests (optional), asks, and gets a short list
   * of places. Nothing is added until "+" is pressed: suggestions are a list to
   * choose from, never edits to the plan. "More" asks again without the ones
   * already shown. The last list for each stop or day is remembered until the
   * page is reloaded, and a booked stay that is on the map gives each placed
   * card its distance; the map toggle shows the placed cards around it.
   */
  import { suggestionsApi } from '../api/client';
  import { t, locale } from '../lib/i18n';
  import { formatKm, kmBetween } from '../lib/distance';
  import PlanMap, { type MapPoint } from './PlanMap.svelte';

  interface Props {
    tripId: string;
    /** What the list is for: a stop (its whole stay) or a day. */
    target: { stopId?: string | null; date?: string | null; label: string };
    /** Adds one suggestion to the plan; the planner owns the write. Resolves
     * to the pin it got, or null when the map does not know the place. */
    onAdd: (s: Suggestion) => Promise<{ lat: number; lon: number } | null>;
    onclose: () => void;
    /** What the plan already has on the map, drawn grey beside the
     * suggestions so a pick can be judged by what is near it. */
    existing?: { id: string; title: string; lat: number; lon: number }[];
  }
  const { tripId, target, onAdd, onclose, existing = [] }: Props = $props();

  const INTERESTS: { key: SuggestInterest; icon: string }[] = [
    { key: 'sights', icon: '📸' },
    { key: 'food', icon: '🍽' },
    { key: 'museums', icon: '🏛' },
    { key: 'nature', icon: '🌳' },
    { key: 'nightlife', icon: '🌙' },
    { key: 'kids', icon: '👶' },
    { key: 'budget', icon: '💸' },
  ];
  const TIME_ICON: Record<Suggestion['best_time'], string> = {
    morning: '🌅',
    afternoon: '☀️',
    evening: '🌙',
    any: '',
  };

  // svelte-ignore state_referenced_locally
  const key = `${tripId}|${target.stopId ?? ''}|${target.date ?? ''}`;
  const kept = memory.get(key);

  let picked = $state<Set<SuggestInterest>>(new Set(kept?.picked));
  let wish = $state(kept?.wish ?? '');
  let loading = $state(false);
  let error = $state<string | null>(null);
  let results = $state<Suggestion[]>(kept?.results ?? []);
  let city = $state(kept?.city ?? '');
  let stay = $state(kept?.stay ?? null);
  let stayWithoutPin = $state<string | null>(kept?.stayWithoutPin ?? null);
  let asked = $state(!!kept);
  /** Keyed on title: what was added, and what is being added right now. */
  let added = $state<Set<string>>(new Set(kept?.added));
  /** Added, but the map did not know the place: on the plan without a pin. */
  let unpinned = $state<Set<string>>(new Set(kept?.unpinned));
  let adding = $state<Set<string>>(new Set());
  /** The card being looked at on the map, by title. */
  let selected = $state<string | null>(null);
  let selectCount = $state(0);

  $effect(() => {
    if (!asked) return;
    memory.set(key, {
      picked: [...picked],
      wish,
      results: $state.snapshot(results) as Suggestion[],
      city,
      stay,
      stayWithoutPin,
      added: [...added],
      unpinned: [...unpinned],
    });
  });

  /** Cards with a position, numbered as the map numbers them. */
  const placed = $derived(results.filter((s) => s.lat != null && s.lon != null));
  const numberOf = (s: Suggestion) => placed.indexOf(s) + 1;

  function distance(s: Suggestion): string | null {
    if (!stay || s.lat == null || s.lon == null) return null;
    return formatKm(kmBetween([stay.lat, stay.lon], [s.lat, s.lon]), $locale ?? 'en');
  }

  const SUGGESTED = '#0ea5e9';
  const ADDED = '#16a34a';
  const PLANNED = '#94a3b8';

  const mapPoints = $derived.by<MapPoint[]>(() => {
    // The plan's own places first, so the suggestions draw on top of them.
    const out: MapPoint[] = existing.map((e) => ({
      id: `plan-${e.id}`,
      kind: 'item',
      title: e.title,
      lat: e.lat,
      lon: e.lon,
      active: false,
      color: PLANNED,
      label: '',
    }));
    placed.forEach((s, i) => {
      out.push({
        id: s.title,
        kind: 'item',
        title: s.title,
        lat: s.lat as number,
        lon: s.lon as number,
        active: true,
        highlight: selected === s.title,
        color: added.has(s.title) ? ADDED : SUGGESTED,
        label: String(i + 1),
      });
    });
    if (stay) out.push({ id: '__stay', kind: 'stay', title: stay.name, lat: stay.lat, lon: stay.lon, active: false });
    return out;
  });
  /** All the suggestions (and the stay) in view; one card when it is picked. */
  const mapFocus = $derived.by<[number, number][]>(() => {
    const one = placed.find((s) => s.title === selected);
    if (one) return [[one.lat as number, one.lon as number]];
    const pts = placed.map((s) => [s.lat as number, s.lon as number] as [number, number]);
    if (stay) pts.push([stay.lat, stay.lon]);
    return pts;
  });

  function showOnMap(s: Suggestion) {
    selected = s.title;
    selectCount += 1;
    // The map is pinned to the top of the panel; bring it into view if the
    // panel scrolled past it.
    document.querySelector('.sg-map')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function pointClicked(p: MapPoint) {
    const n = placed.findIndex((s) => s.title === p.id) + 1;
    if (!n) return;
    selected = p.id;
    document.getElementById(`sg-card-${n}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function toggle(key: SuggestInterest) {
    const next = new Set(picked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    picked = next;
  }

  const ERRORS: Record<string, string> = {
    daily_limit: 'suggest.error_daily_limit',
    place_unknown: 'suggest.error_place_unknown',
    ai_unreachable: 'suggest.error_unreachable',
    ai_misconfigured: 'suggest.error_misconfigured',
    ai_bad_answer: 'suggest.error_bad_answer',
    ai_not_configured: 'suggest.error_misconfigured',
  };

  async function ask(more = false) {
    if (loading) return;
    loading = true;
    error = null;
    try {
      const r = await suggestionsApi.suggest(tripId, {
        stop_id: target.stopId ?? null,
        date: target.date ?? null,
        interests: [...picked],
        wish: wish.trim() || null,
        exclude: more ? results.map((s) => s.title) : [],
      });
      results = more ? [...results, ...r.suggestions] : r.suggestions;
      city = r.city;
      stay = r.stay ?? null;
      stayWithoutPin = r.stay_without_pin ?? null;
      asked = true;
    } catch (err) {
      const code = (err as Error).message;
      error = ERRORS[code] ? $t(ERRORS[code]) : $t('suggest.error_generic');
    } finally {
      loading = false;
    }
  }

  async function add(s: Suggestion) {
    if (added.has(s.title) || adding.has(s.title)) return;
    adding = new Set(adding).add(s.title);
    try {
      const pin = await onAdd(s);
      added = new Set(added).add(s.title);
      if (!pin) unpinned = new Set(unpinned).add(s.title);
      else if (s.lat == null) {
        // Found on the map just now: the card gets its distance and its pin.
        results = results.map((r) => (r.title === s.title ? { ...r, lat: pin.lat, lon: pin.lon } : r));
      }
    } catch {
      error = $t('suggest.error_add');
    } finally {
      const next = new Set(adding);
      next.delete(s.title);
      adding = next;
    }
  }

  /** Google Maps for this place, where its photos and reviews are. Opened only
   * when clicked: nothing about the trip goes to Google otherwise. */
  function mapsLink(s: Suggestion): string {
    const query = [s.title, city].filter(Boolean).join(', ');
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
  }

  function keydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onclose();
  }

  /** Focus moves into the dialog so Escape and the keyboard reach it. */
  function focusOnOpen(node: HTMLElement) {
    node.focus();
  }
</script>

<!-- Escape on the window too: a card's "+" disables itself once pressed, and a
     disabled button drops focus to the page, out of the dialog's own handler. -->
<svelte:window onkeydown={keydown} />

<div class="sg-backdrop" role="presentation" onclick={onclose}>
  <div
    class="sg-modal"
    role="dialog"
    aria-modal="true"
    aria-labelledby="sg-title"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => {
      if (e.key === 'Escape') {
        e.stopPropagation(); // the window's handler would close it a second time
        onclose();
      }
    }}
    use:focusOnOpen
  >
    <button class="sg-close" type="button" aria-label={$t('organizer.close')} onclick={onclose}>✕</button>
    <h2 id="sg-title">✨ {$t('suggest.title', { values: { place: target.label } })}</h2>

    <div class="sg-chips" role="group" aria-label={$t('suggest.interests')}>
      {#each INTERESTS as it (it.key)}
        <button
          type="button"
          class="sg-chip"
          class:on={picked.has(it.key)}
          aria-pressed={picked.has(it.key)}
          onclick={() => toggle(it.key)}
        >{it.icon} {$t(`suggest.interest_${it.key}`)}</button>
      {/each}
    </div>

    <form class="sg-ask" onsubmit={(e) => { e.preventDefault(); ask(false); }}>
      <input
        class="form-input"
        maxlength="200"
        placeholder={$t('suggest.wish_placeholder')}
        aria-label={$t('suggest.wish_placeholder')}
        bind:value={wish}
        enterkeyhint="search"
      />
      <button class="btn btn-primary btn-sm" type="submit" disabled={loading}>
        {loading && !results.length ? $t('suggest.thinking') : $t('suggest.ask')}
      </button>
    </form>

    {#if error}<p class="sg-error" role="alert">{error}</p>{/if}

    {#if loading && !results.length}
      <p class="sg-hint" aria-live="polite">{$t('suggest.thinking_hint')}</p>
    {/if}

    {#if results.length}
      {#if placed.length}
        <div class="sg-map">
          <PlanMap
            compact
            cities={[]}
            points={mapPoints}
            lines={[]}
            focus={mapFocus}
            pointZoom={16}
            focusKey={selectCount}
            onPointClick={pointClicked}
          />
          <p class="sg-legend">
            <span><i style="background:{SUGGESTED}"></i>{$t('suggest.legend_suggested')}</span>
            <span><i style="background:{ADDED}"></i>{$t('suggest.legend_added')}</span>
            {#if existing.length}<span><i style="background:{PLANNED}"></i>{$t('suggest.legend_planned')}</span>{/if}
            {#if stay}<span>🏨 {stay.name}</span>{/if}
          </p>
        </div>
      {/if}
      {#if stayWithoutPin}
        <p class="sg-hint sg-stay-hint">🏨 {$t('suggest.stay_without_pin', { values: { stay: stayWithoutPin } })}</p>
      {/if}
      <ul class="sg-list">
        {#each results as s (s.title)}
          {@const n = numberOf(s)}
          {@const far = distance(s)}
          <li class="sg-card" class:selected={selected === s.title} id={n ? `sg-card-${n}` : undefined}>
            {#if s.image_url}
              <a class="sg-thumb" href={s.image_page || s.image_url} target="_blank" rel="noopener noreferrer" title={$t('suggest.photo_source')}>
                <img src={s.image_url} alt={s.title} loading="lazy" referrerpolicy="no-referrer" />
              </a>
            {/if}
            <div class="sg-card-body">
              <div class="sg-card-title">{#if n}<span class="sg-num" style="background:{added.has(s.title) ? ADDED : SUGGESTED}">{n}</span>{/if}{s.title}</div>
              <p class="sg-why">{s.why}</p>
              <div class="sg-meta">
                {#if TIME_ICON[s.best_time]}<span>{TIME_ICON[s.best_time]} {$t(`suggest.time_${s.best_time}`)}</span>{/if}
                {#if far && stay}<span class="sg-far" title={$t('suggest.distance_hint')}>🛏 {$t('suggest.from_stay', { values: { distance: far, stay: stay.name } })}</span>{/if}
                <a class="sg-photos" href={mapsLink(s)} target="_blank" rel="noopener noreferrer">📷 {$t('suggest.photos')}</a>
              </div>
              {#if unpinned.has(s.title)}<p class="sg-unpinned">{$t('suggest.added_without_pin')}</p>{/if}
            </div>
            <div class="sg-actions">
            <button
              type="button"
              class="btn btn-sm sg-add"
              class:btn-secondary={!added.has(s.title)}
              disabled={added.has(s.title) || adding.has(s.title)}
              aria-label={$t('suggest.add', { values: { name: s.title } })}
              onclick={() => add(s)}
            >{added.has(s.title) ? '✓' : '+'}</button>
            {#if n}
              <button
                type="button"
                class="btn btn-sm btn-secondary sg-show"
                class:on={selected === s.title}
                aria-pressed={selected === s.title}
                aria-label={$t('suggest.show_map_named', { values: { name: s.title } })}
                title={$t('suggest.show_map')}
                onclick={() => showOnMap(s)}
              >📍</button>
            {/if}
            </div>
          </li>
        {/each}
      </ul>
      <button class="btn btn-secondary btn-sm sg-more" type="button" disabled={loading} onclick={() => ask(true)}>
        {loading ? $t('suggest.thinking') : $t('suggest.more')}
      </button>
    {:else if asked && !loading && !error}
      <p class="sg-hint">{$t('suggest.none')}</p>
    {/if}

    {#if asked}
      <p class="sg-foot">
        {$t('suggest.disclaimer')}
      </p>
    {/if}
  </div>
</div>

<style>
  .sg-backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.4);
    display: grid;
    place-items: center;
    /* Above the tab bar and the side rail, like the planner's other dialogs. */
    z-index: 500;
    padding: 16px 0;
  }
  .sg-modal {
    position: relative;
    max-height: calc(100dvh - 32px);
    overflow-y: auto;
    background: var(--bg-card);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    width: min(520px, calc(100vw - 32px));
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
    box-shadow: var(--shadow-elevated);
  }
  .sg-modal h2 {
    margin: 0 28px 0 0;
    font-size: 1.1rem;
  }
  .sg-close {
    position: absolute;
    top: 10px;
    right: 10px;
    border: none;
    background: none;
    font-size: 1rem;
    cursor: pointer;
    color: var(--text-muted);
  }
  .sg-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  /* Neutral pills: picking an interest is a choice, not a status. */
  .sg-chip {
    font: inherit;
    font-size: 0.8rem;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-primary);
    cursor: pointer;
  }
  .sg-chip.on {
    border-color: var(--text-primary);
    background: var(--bg-subtle, var(--surface-alt));
    font-weight: 600;
  }
  .sg-ask {
    display: flex;
    gap: var(--space-xs, 6px);
  }
  .sg-ask .form-input {
    flex: 1;
    min-width: 0;
  }
  .sg-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sg-card {
    display: flex;
    gap: var(--space-sm);
    align-items: flex-start;
    padding: 8px 10px;
    border: 1px solid var(--border-light, var(--border));
    border-radius: var(--radius-sm);
  }
  .sg-thumb {
    flex: none;
    width: 72px;
    height: 72px;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--bg-subtle, var(--surface-alt));
  }
  .sg-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .sg-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    margin-top: 4px;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .sg-photos {
    color: var(--accent-text);
  }
  /* Pinned to the top of the panel while the cards scroll under it, so
     "show on map" always lands somewhere visible. */
  .sg-map {
    position: sticky;
    top: calc(-1 * var(--space-lg));
    z-index: 2;
    margin: 0 calc(-1 * var(--space-lg));
    padding: var(--space-sm) var(--space-lg) 6px;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border-light, var(--border));
  }
  .sg-map :global(.plan-map) {
    border-radius: var(--radius-sm);
  }
  .sg-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    margin: 4px 0 0;
    font-size: 0.7rem;
    color: var(--text-muted);
  }
  .sg-legend i {
    display: inline-block;
    width: 9px;
    height: 9px;
    margin-right: 4px;
    border-radius: 50%;
    vertical-align: -1px;
  }
  .sg-card.selected {
    border-color: #0ea5e9;
    box-shadow: 0 0 0 1px #0ea5e9;
  }
  .sg-actions {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .sg-show {
    min-width: 2.25rem;
  }
  .sg-show.on {
    border-color: #0ea5e9;
    box-shadow: 0 0 0 1px #0ea5e9;
  }
  .sg-num {
    display: inline-grid;
    place-items: center;
    width: 18px;
    height: 18px;
    margin-right: 6px;
    border-radius: 50%;
    background: #0ea5e9;
    color: #fff;
    font-size: 0.7rem;
    vertical-align: 1px;
  }
  .sg-unpinned {
    margin: 4px 0 0;
    font-size: 0.75rem;
    color: var(--warning-text, var(--text-secondary));
  }
  .sg-card-body {
    flex: 1;
    min-width: 0;
  }
  .sg-card-title {
    font-weight: 600;
    font-size: 0.9rem;
  }
  .sg-why {
    margin: 2px 0 0;
    font-size: 0.8rem;
    color: var(--text-secondary);
  }
  .sg-add {
    flex: none;
    min-width: 2.25rem;
  }
  .sg-more {
    align-self: flex-start;
  }
  .sg-hint,
  .sg-foot {
    margin: 0;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
  .sg-error {
    margin: 0;
    font-size: 0.85rem;
    color: var(--danger-text);
  }
  @media (max-width: 760px) {
    .sg-ask .form-input {
      font-size: 16px; /* below 16px iOS zooms in on focus */
    }
  }
</style>
