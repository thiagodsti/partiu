/* One colour per city of a trip's route, in route order, shared by the planner
 * and the trip page's day cards so a city reads the same on both. */
export const PLAN_COLORS = ['#e76f51', '#2a9d8f', '#e9c46a', '#8e7dbe', '#f4a261', '#457b9d', '#90be6d', '#d1495b'];

export function stopColor<T extends { id: string }>(stops: T[], stop: T): string {
  const i = stops.findIndex((s) => s.id === stop.id);
  return PLAN_COLORS[Math.max(0, i) % PLAN_COLORS.length];
}
