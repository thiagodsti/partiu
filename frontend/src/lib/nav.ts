export type NavIconName = 'plane' | 'clock' | 'chart' | 'inbox' | 'sliders';

export interface NavItem {
  /** Route prefix the item points at. */
  href: string;
  icon: NavIconName;
  /** Locale key for the label. */
  label: string;
  /** Route prefixes that should light this item up. */
  match: string[];
  /** Whether the unread/invitation count rides on this item. */
  badge?: boolean;
}

/**
 * One list, read by both the desktop rail and the mobile dock, so the two
 * can never drift apart on order, labels or which route is active.
 */
export const NAV_ITEMS: NavItem[] = [
  { href: '#/trips', icon: 'plane', label: 'nav.trips', match: ['/', '/trips'] },
  { href: '#/history', icon: 'clock', label: 'nav.history', match: ['/history'] },
  { href: '#/stats', icon: 'chart', label: 'nav.stats', match: ['/stats'] },
  { href: '#/notifications', icon: 'inbox', label: 'nav.notifications', match: ['/notifications'], badge: true },
  { href: '#/settings', icon: 'sliders', label: 'nav.settings', match: ['/settings'] },
];

export function isActive(item: NavItem, location: string): boolean {
  return item.match.some((m) => (m === '/' ? location === '/' : location.startsWith(m)));
}
