<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { Map as LeafletMap } from 'leaflet';
  import type { Flight } from '../api/types';
  import { airportsApi } from '../api/client';

  interface Props {
    flights: Flight[];
  }

  const { flights }: Props = $props();

  let mapEl: HTMLDivElement | undefined = $state();
  let map: LeafletMap | null = null;

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
    if (!mapEl || flights.length === 0) return;

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
      if (validCodes.length === 0) return;

      leafletMap = L.map(mapEl, {
        zoomControl: true,
        attributionControl: true,
        scrollWheelZoom: false,
        // Disable drag on touch so the map doesn't trap page scrolling on mobile
        dragging: !L.Browser.touch,
      });
      map = leafletMap;

      // Voyager tiles with OSM fallback if blocked by adblocker
      const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      });

      let switchedToOsm = false;
      const cartoLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      });

      cartoLayer.on('tileerror', () => {
        if (!switchedToOsm) {
          switchedToOsm = true;
          leafletMap!.removeLayer(cartoLayer);
          osmLayer.addTo(leafletMap!);
        }
      });

      cartoLayer.addTo(leafletMap);

      // Draw arcs — two layers for a glow effect
      for (const flight of flights) {
        const dep = coords[flight.departure_airport];
        const arr = coords[flight.arrival_airport];
        if (!dep || !arr) continue;
        const pts = greatCirclePoints(dep.lat, dep.lon, arr.lat, arr.lon);
        // Glow layer
        L.polyline(pts, { color: '#3b82f6', weight: 10, opacity: 0.15, lineCap: 'round' }).addTo(leafletMap);
        // Main line
        L.polyline(pts, { color: '#3b82f6', weight: 2.5, opacity: 0.9, lineCap: 'round' }).addTo(leafletMap);
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

      const latLngs = validCodes.map((c) => L.latLng(coords[c].lat, coords[c].lon));
      leafletMap.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40] });
    })();

    return () => {
      destroyed = true;
      leafletMap?.remove();
      map = null;
    };
  });

  onDestroy(() => {
    map?.remove();
    map = null;
  });
</script>

<div class="trip-map" bind:this={mapEl}></div>

<style>
  .trip-map {
    width: 100%;
    height: 280px;
    border-radius: var(--radius-lg, 12px);
    overflow: hidden;
    margin-bottom: var(--space-md);
    background: var(--surface, #f0f0f0);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  }
</style>
