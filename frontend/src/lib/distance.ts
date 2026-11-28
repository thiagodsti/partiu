/** Great-circle distance in kilometres (haversine; a sphere is plenty for "how
 * far is this from the hotel"). */
export function kmBetween(a: [number, number], b: [number, number]): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b[0] - a[0]);
  const dLon = rad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** "350 m", "1.2 km", "14 km" — straight-line, so no false precision. */
export function formatKm(km: number, locale = 'en'): string {
  if (km < 1) return `${Math.max(100, Math.round((km * 1000) / 50) * 50)} m`;
  const n = km < 10 ? Math.round(km * 10) / 10 : Math.round(km);
  return `${n.toLocaleString(locale, { maximumFractionDigits: 1 })} km`;
}
