import { describe, it, expect } from 'vitest';
import { NAV_ITEMS, isActive, type NavItem } from './nav';

function item(href: string): NavItem {
  const found = NAV_ITEMS.find((i) => i.href === href);
  if (!found) throw new Error(`no nav item for ${href}`);
  return found;
}

describe('NAV_ITEMS', () => {
  it('has a unique href per entry', () => {
    const hrefs = NAV_ITEMS.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('marks exactly one entry as carrying the inbox count', () => {
    expect(NAV_ITEMS.filter((i) => i.badge)).toHaveLength(1);
    expect(NAV_ITEMS.find((i) => i.badge)?.href).toBe('#/notifications');
  });
});

describe('isActive', () => {
  it('lights Trips on the bare root', () => {
    expect(isActive(item('#/trips'), '/')).toBe(true);
  });

  it('lights Trips on a nested trip route', () => {
    expect(isActive(item('#/trips'), '/trips/abc/flights/xyz')).toBe(true);
  });

  // The root match is exact: '/history' starts with neither '/' as a prefix
  // rule nor '/trips', and matching '/' loosely would light Trips everywhere.
  it('does not light Trips on another section', () => {
    expect(isActive(item('#/trips'), '/history')).toBe(false);
    expect(isActive(item('#/trips'), '/settings')).toBe(false);
  });

  it('lights History on a trip opened from history', () => {
    expect(isActive(item('#/history'), '/history/abc')).toBe(true);
    expect(isActive(item('#/history'), '/trips/abc')).toBe(false);
  });

  it('lights Stats on the world map, which lives under it', () => {
    expect(isActive(item('#/stats'), '/stats/map')).toBe(true);
  });

  it('leaves every entry dark on a route the navigation does not own', () => {
    expect(NAV_ITEMS.filter((i) => isActive(i, '/login'))).toHaveLength(0);
  });
});
