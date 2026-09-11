<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import 'leaflet/dist/leaflet.css';
  import type { Map as LeafletMap } from 'leaflet';
  import type { Flight, TripSegment, SegmentType } from '../api/types';
  import { airportsApi } from '../api/client';
  import { currentUser } from '../lib/authStore';
  import { t } from '../lib/i18n';
  import { escapeHtml } from '../lib/utils';

  interface Props {
    flights: Flight[];
    segments?: TripSegment[];
  }

  const { flights, segments = [] }: Props = $props();

  const FLIGHT_COLOR = '#3b82f6';

  /** Consecutive tile failures, with none ever having loaded, before the
   * basemap is treated as blocked. A blocked layer fails every one of the
   * dozen-odd tiles a viewport asks for, so this trips immediately; a flaky
   * connection does not reach it without also landing a success. */
  const UNREACHABLE_TILE_FAILURES = 4;

  // Ground legs get their own hue so a train is distinguishable from a flight
  // at a glance, and are drawn as dashed straight lines rather than
  // great-circle arcs — a train does not fly the geodesic.
  const SEGMENT_COLORS: Record<SegmentType, string> = {
    train: '#10b981',
    bus: '#f59e0b',
    ferry: '#06b6d4',
    car: '#8b5cf6',
  };

  /** Only segments with coordinates at both ends can be drawn; a hand-typed
   * place has none, and is silently skipped rather than mis-plotted. */
  function mappableSegments(list: TripSegment[]) {
    return list.filter(
      (s) =>
        s.departure.lat != null && s.departure.lon != null &&
        s.arrival.lat != null && s.arrival.lon != null,
    );
  }

  let mapEl: HTMLDivElement | undefined = $state();
  let map: LeafletMap | null = null;

  // A full-width map that answers vertical swipes traps the page scroll on a
  // phone, so panning starts off on touch devices — which used to mean it could
  // never be turned on. The control below is that switch. Matches what
  // L.Browser.touch decides, but is readable before Leaflet is imported, so the
  // map can be created already in the right state instead of flipping after.
  const isTouchDevice =
    typeof window !== 'undefined' &&
    ('ontouchstart' in window || (navigator.maxTouchPoints ?? 0) > 0);

  let panEnabled = $state(!isTouchDevice);

  function setPanEnabled(on: boolean) {
    panEnabled = on;
    // Wheel zoom stays off in both states: unlike dragging it has no gesture of
    // its own to trap, it steals the page's scroll outright. Zooming is the
    // +/- control and pinch, which both keep working while panning is off.
    if (on) map?.dragging.enable();
    else map?.dragging.disable();
  }

  // Great-circle intermediate points for a curved arc
  function greatCirclePoints(
    lat1: number, lon1: number,
    lat2: number, lon2: number,
    n = 80,
  ): [number, number][] {
    const toRad = (d: number) => (d * Math.PI) / 180;
    const toDeg = (r: number) => (r * 180) / Math.PI;
    const φ1 = toRad(lat1), λ1 = toRad(lon1);
    const φ2 = toRad(lat2), λ2 = toRad(lon2);
    const Δφ = φ2 - φ1, Δλ = λ2 - λ1;
    const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
    const d = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    if (d < 0.0001) return [[lat1, lon1]];
    const pts: [number, number][] = [];
    for (let i = 0; i <= n; i++) {
      const f = i / n;
      const A = Math.sin((1 - f) * d) / Math.sin(d);
      const B = Math.sin(f * d) / Math.sin(d);
      const x = A * Math.cos(φ1) * Math.cos(λ1) + B * Math.cos(φ2) * Math.cos(λ2);
      const y = A * Math.cos(φ1) * Math.sin(λ1) + B * Math.cos(φ2) * Math.sin(λ2);
      const z = A * Math.sin(φ1) + B * Math.sin(φ2);
      pts.push([toDeg(Math.atan2(z, Math.sqrt(x ** 2 + y ** 2))), toDeg(Math.atan2(y, x))]);
    }
    return pts;
  }

  $effect(() => {
    const drawableSegments = mappableSegments(segments);
    // Read synchronously so the effect re-runs (and rebuilds the map) if the
    // key arrives after the first paint; inside the async block below it would
    // not register as a dependency.
    const cartoKey = $currentUser?.carto_api_key ?? '';
    if (!mapEl || (flights.length === 0 && drawableSegments.length === 0)) return;

    const codes = [...new Set(flights.flatMap((f) => [f.departure_airport, f.arrival_airport]))];

    let destroyed = false;
    let leafletMap: LeafletMap | null = null;

    (async () => {
      const [L, airportResults] = await Promise.all([
        import('leaflet'),
        Promise.all(codes.map((c) => airportsApi.get(c).catch(() => null))),
      ]);

      if (destroyed || !mapEl) return;

      const coords: Record<string, { lat: number; lon: number; name: string; city: string }> = {};
      codes.forEach((code, i) => {
        const a = airportResults[i];
        if (a?.latitude != null && a?.longitude != null) {
          coords[code] = { lat: a.latitude, lon: a.longitude, name: a.name, city: a.city_name ?? code };
        }
      });

      const validCodes = Object.keys(coords);
      if (validCodes.length === 0 && drawableSegments.length === 0) return;

      leafletMap = L.map(mapEl, {
        zoomControl: true,
        attributionControl: true,
        scrollWheelZoom: false,
        // untrack: the toggle must not be a dependency of this effect, or
        // flipping it would tear the whole map down and rebuild it.
        dragging: untrack(() => panEnabled),
      });
      map = leafletMap;

      const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      });

      // Voyager tiles, but only with a key: CARTO stopped serving unkeyed
      // raster tiles in 2026 and now stamps them "API KEY REQUIRED" — served as
      // a normal 200, so the tileerror fallback below never fires on them and
      // the watermark would just sit on the map. Without a key we go straight
      // to OSM; the fallback still covers a keyed layer blocked by an adblocker.
      if (cartoKey) {
        const cartoLayer = L.tileLayer(
          'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png' +
            `?key=${encodeURIComponent(cartoKey)}`,
          {
            attribution: '© <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19,
          },
        );

        // The fallback is for a CARTO that is *unreachable* — blocked by an
        // adblocker or a DNS filter — not for a tile that happened to drop.
        // Demoting on the first tileerror meant one lost request on a phone
        // swapped the whole basemap for OSM, whose labels are in the local
        // language (上海, not SHANGHAI) — which is how a working map turned
        // Chinese on mobile and stayed Latin on a desktop that never dropped a
        // tile. A layer that has drawn even one tile is reachable, so it is
        // never demoted; a blocked one draws none and fails every request.
        let switchedToOsm = false;
        let anyTileLoaded = false;
        let failedTiles = 0;

        cartoLayer.on('tileload', () => {
          anyTileLoaded = true;
        });

        cartoLayer.on('tileerror', () => {
          if (switchedToOsm || anyTileLoaded) return;
          failedTiles += 1;
          if (failedTiles < UNREACHABLE_TILE_FAILURES) return;
          switchedToOsm = true;
          leafletMap!.removeLayer(cartoLayer);
          osmLayer.addTo(leafletMap!);
        });

        cartoLayer.addTo(leafletMap);
      } else {
        osmLayer.addTo(leafletMap);
      }

      // Draw arcs — two layers for a glow effect
      for (const flight of flights) {
        const dep = coords[flight.departure_airport];
        const arr = coords[flight.arrival_airport];
        if (!dep || !arr) continue;
        const pts = greatCirclePoints(dep.lat, dep.lon, arr.lat, arr.lon);
        // Glow layer
        L.polyline(pts, { color: FLIGHT_COLOR, weight: 10, opacity: 0.15, lineCap: 'round' }).addTo(leafletMap);
        // Main line
        L.polyline(pts, { color: FLIGHT_COLOR, weight: 2.5, opacity: 0.9, lineCap: 'round' }).addTo(leafletMap);
      }

      // Ground legs: straight dashed lines, coloured by transport type.
      const segmentPoints: [number, number][] = [];
      for (const seg of drawableSegments) {
        const from: [number, number] = [seg.departure.lat!, seg.departure.lon!];
        const to: [number, number] = [seg.arrival.lat!, seg.arrival.lon!];
        const color = SEGMENT_COLORS[seg.type] ?? FLIGHT_COLOR;
        L.polyline([from, to], {
          color,
          weight: 3,
          opacity: 0.9,
          dashArray: '7 6',
          lineCap: 'round',
        }).addTo(leafletMap);
        segmentPoints.push(from, to);

        for (const [point, name] of [
          [from, seg.departure.name] as const,
          [to, seg.arrival.name] as const,
        ]) {
          const icon = L.divIcon({
            className: '',
            html: `
              <div style="
                width:9px;height:9px;border-radius:2px;
                background:${color};border:2px solid #fff;
                box-shadow:0 2px 6px rgba(0,0,0,.35);
                transform:translate(-50%,-50%);
              "></div>`,
            iconSize: [0, 0],
            iconAnchor: [0, 0],
          });
          // bindTooltip renders its string as HTML, and a segment's place name is
          // free user text (unlike the airport names below, which come from the
          // airports table) — so it has to be escaped.
          L.marker(point, { icon })
            .bindTooltip(escapeHtml(name), { direction: 'top', offset: [0, -10], opacity: 0.95 })
            .addTo(leafletMap);
        }
      }

      // Airport markers with IATA label
      for (const code of validCodes) {
        const { lat, lon, city } = coords[code];
        const icon = L.divIcon({
          className: '',
          html: `
            <div style="position:relative;width:0;height:0">
              <div style="
                width:11px;height:11px;border-radius:50%;
                background:#3b82f6;border:2.5px solid #fff;
                box-shadow:0 2px 8px rgba(59,130,246,.5);
                position:absolute;transform:translate(-50%,-50%);
              "></div>
              <span style="
                position:absolute;top:8px;left:50%;transform:translateX(-50%);
                font-size:10px;font-weight:700;letter-spacing:.03em;
                color:#1e3a5f;background:rgba(255,255,255,.88);
                padding:1px 5px;border-radius:4px;white-space:nowrap;
                box-shadow:0 1px 3px rgba(0,0,0,.15);
              ">${code}</span>
            </div>`,
          iconSize: [0, 0],
          iconAnchor: [0, 0],
        });
        L.marker([lat, lon], { icon })
          .bindTooltip(`<b>${code}</b> · ${city}`, { direction: 'top', offset: [0, -14], opacity: 0.95 })
          .addTo(leafletMap);
      }

      const latLngs = [
        ...validCodes.map((c) => L.latLng(coords[c].lat, coords[c].lon)),
        ...segmentPoints.map(([lat, lon]) => L.latLng(lat, lon)),
      ];
      if (latLngs.length === 0) return;
      leafletMap.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40] });
    })();

    return () => {
      destroyed = true;
      leafletMap?.remove();
      map = null;
    };
  });

  function onBeforePrint() {
    map?.invalidateSize();
  }

  onMount(() => {
    window.addEventListener('beforeprint', onBeforePrint);
  });

  onDestroy(() => {
    window.removeEventListener('beforeprint', onBeforePrint);
    map?.remove();
    map = null;
  });
</script>

<div class="trip-map-wrap">
  <div class="trip-map" bind:this={mapEl}></div>
  <button
    type="button"
    class="map-pan-toggle"
    class:map-pan-on={panEnabled}
    aria-pressed={panEnabled}
    onclick={() => setPanEnabled(!panEnabled)}
  >
    {panEnabled ? `🔒 ${$t('map.lock')}` : `✋ ${$t('map.unlock')}`}
  </button>
</div>

<style>
  .trip-map-wrap {
    position: relative;
  }

  .trip-map {
    width: 100%;
    height: 280px;
    border-radius: var(--radius-lg, 12px);
    overflow: hidden;
    margin-bottom: var(--space-md);
    background: var(--surface, #f0f0f0);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
    isolation: isolate;
  }

  /* Leaflet's own controls sit at z-index 800-1000, so this has to clear them
     as well as the tile panes. Top-right keeps it clear of the zoom control. */
  .map-pan-toggle {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 1000;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 9px;
    border: 1px solid rgba(0, 0, 0, 0.18);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.94);
    color: #1e293b;
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1.5;
    cursor: pointer;
    box-shadow: 0 1px 5px rgba(0, 0, 0, 0.25);
  }

  .map-pan-toggle:hover {
    background: #fff;
  }

  .map-pan-on {
    background: rgba(59, 130, 246, 0.94);
    border-color: rgba(59, 130, 246, 0.5);
    color: #fff;
  }

  .map-pan-on:hover {
    background: rgba(59, 130, 246, 1);
  }

  @media print {
    .map-pan-toggle {
      display: none;
    }

    .trip-map {
      height: 260px;
      border-radius: 0;
      box-shadow: none;
      border: 1px solid #e2e8f0;
      break-inside: avoid;
    }

    .trip-map :global(.leaflet-control-attribution) {
      display: none !important;
    }
  }
</style>
