<script lang="ts" module>
  export interface MapCity {
    name: string;
    lat: number;
    lon: number;
    color: string;
    /** 1-based position on the route. */
    order: number;
    nights: number;
  }
  export interface MapPoint {
    id: string;
    kind: 'stay' | 'item';
    title: string;
    lat: number;
    lon: number;
    /** Highlighted: belongs to the selected day. */
    active: boolean;
    color?: string;
    label?: string;
  }
  export interface MapLine {
    id: string;
    from: [number, number];
    to: [number, number];
    color: string;
  }
</script>

<script lang="ts">
  /* The organizer's map: the route as numbered city markers joined in order,
   * the stays and the plan items that have a place, and the ground legs. It is
   * redrawn from props, so whatever the board changes shows up here at once;
   * `focus` re-fits the view when the selected day or city changes. */
  import { onDestroy, onMount } from 'svelte';
  import 'leaflet/dist/leaflet.css';
  import type { LayerGroup, Map as LeafletMap } from 'leaflet';
  import { escapeHtml } from '../lib/utils';

  interface Props {
    cities: MapCity[];
    points: MapPoint[];
    lines: MapLine[];
    /** Coordinates to fit the view to; empty fits everything. */
    focus: [number, number][];
    onCityClick?: (name: string) => void;
    onPointClick?: (point: MapPoint) => void;
  }
  const { cities, points, lines, focus, onCityClick, onPointClick }: Props = $props();

  let mapEl: HTMLDivElement | undefined = $state();
  let map: LeafletMap | null = $state(null);
  let layer: LayerGroup | null = null;
  let L: typeof import('leaflet') | null = null;

  onMount(async () => {
    L = await import('leaflet');
    if (!mapEl) return;
    const m = L.map(mapEl, { zoomControl: true, scrollWheelZoom: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(m);
    m.setView([30, 110], 3);
    layer = L.layerGroup().addTo(m);
    map = m;
  });

  onDestroy(() => {
    map?.remove();
    map = null;
  });

  $effect(() => {
    // Read every prop so the effect re-runs on any change.
    const cs = cities;
    const ps = points;
    const ls = lines;
    if (!map || !layer || !L) return;
    const Lf = L;
    layer.clearLayers();

    if (cs.length > 1) {
      Lf.polyline(
        cs.map((c) => [c.lat, c.lon] as [number, number]),
        { color: '#64748b', weight: 3, opacity: 0.7, dashArray: '2 8', lineCap: 'round' },
      ).addTo(layer);
    }
    for (const l of ls) {
      Lf.polyline([l.from, l.to], { color: l.color, weight: 3, opacity: 0.9 }).addTo(layer);
    }
    for (const c of cs) {
      const icon = Lf.divIcon({
        className: 'plan-city-icon',
        html: `<div class="plan-city" style="--c:${c.color}"><b>${c.order}</b>${escapeHtml(c.name)}</div>`,
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });
      Lf.marker([c.lat, c.lon], { icon, zIndexOffset: 500 })
        .on('click', () => onCityClick?.(c.name))
        .addTo(layer);
    }
    for (const p of ps) {
      const html =
        p.kind === 'stay'
          ? `<div class="plan-pin stay${p.active ? ' active' : ''}">🏨</div>`
          : `<div class="plan-pin item${p.active ? ' active' : ''}" style="--c:${p.color ?? '#3b82f6'}">${escapeHtml(p.label ?? '')}</div>`;
      const icon = Lf.divIcon({
        className: 'plan-pin-icon',
        html,
        iconSize: p.active ? [26, 26] : [18, 18],
        iconAnchor: p.active ? [13, 13] : [9, 9],
      });
      Lf.marker([p.lat, p.lon], { icon, zIndexOffset: p.active ? 1000 : 0 })
        .bindTooltip(escapeHtml(p.title), { direction: 'top', offset: [0, -10] })
        .on('click', () => onPointClick?.(p))
        .addTo(layer);
    }
  });

  // Re-fit only when the focus changes, not on every redraw, so editing an
  // item does not yank the view away from where the user has panned.
  let lastFocus = '';
  $effect(() => {
    const f = focus;
    const cs = cities;
    if (!map || !L) return;
    const pts = f.length > 0 ? f : cs.map((c) => [c.lat, c.lon] as [number, number]);
    const key = JSON.stringify(pts);
    if (key === lastFocus || pts.length === 0) return;
    lastFocus = key;
    if (pts.length === 1) map.flyTo(pts[0], 12, { duration: 0.6 });
    else map.flyToBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 13, duration: 0.6 });
  });
</script>

<div class="plan-map" bind:this={mapEl}></div>

<style>
  .plan-map {
    width: 100%;
    height: 100%;
    min-height: 320px;
    border-radius: var(--radius-lg);
    overflow: hidden;
    z-index: 0;
  }
  :global(.plan-city-icon),
  :global(.plan-pin-icon) {
    background: none;
    border: none;
  }
  /* A city is a labelled pill centred on its point, unlike the round pins of
   * stays and plan items, so the two never read as the same thing. */
  :global(.plan-city) {
    position: absolute;
    transform: translate(-50%, -50%);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px 3px 3px;
    border-radius: 999px;
    background: #1f2937;
    color: #fff;
    font-weight: 700;
    font-size: 12px;
    white-space: nowrap;
    border: 2px solid var(--c);
    box-shadow: 0 2px 6px rgb(0 0 0 / 0.35);
    cursor: pointer;
  }
  :global(.plan-city b) {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--c);
    display: grid;
    place-items: center;
    font-size: 11px;
  }
  :global(.plan-pin) {
    width: 100%;
    height: 100%;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 10px;
    font-weight: 700;
    box-sizing: border-box;
    box-shadow: 0 1px 4px rgb(0 0 0 / 0.3);
  }
  :global(.plan-pin.stay) {
    background: #fff;
    font-size: 11px;
  }
  :global(.plan-pin.item) {
    background: #fff;
    border: 3px solid var(--c);
    color: #1f2937;
  }
  :global(.plan-pin.item.active) {
    background: var(--c);
    color: #fff;
    border-color: #fff;
    font-size: 12px;
  }
  :global(.plan-pin.stay.active) {
    font-size: 15px;
    outline: 3px solid #f59e0b;
  }
</style>
