import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';

// vi.mock is hoisted above the imports, so the stores it hands back have to be
// created in a hoisted block too — a plain top-level `const` is not defined yet
// when the factory runs, and the block cannot import svelte/store either.
// Both components only ever subscribe, so a two-line store is enough.
const stores = vi.hoisted(() => {
  function store<T>(initial: T) {
    let value = initial;
    const subs = new Set<(v: T) => void>();
    return {
      subscribe(fn: (v: T) => void) {
        subs.add(fn);
        fn(value);
        return () => subs.delete(fn);
      },
      set(v: T) {
        value = v;
        subs.forEach((fn) => fn(value));
      },
    };
  }
  return { location: store('/trips'), badge: store(0) };
});

vi.mock('svelte-spa-router', () => ({ location: stores.location }));
vi.mock('../lib/i18n', () => ({
  t: { subscribe: (fn: (v: (k: string) => string) => void) => { fn((k) => k); return () => {}; } },
}));
vi.mock('../lib/invitationStore', () => ({ totalInboxBadge: stores.badge }));

import SideRail from './SideRail.svelte';
import TabBar from './TabBar.svelte';
import { NAV_ITEMS } from '../lib/nav';

describe('SideRail', () => {
  it('renders one entry per nav item', () => {
    const { container } = render(SideRail);
    expect(container.querySelectorAll('.rail-item')).toHaveLength(NAV_ITEMS.length);
  });

  it('marks the current section active', () => {
    stores.location.set('/trips/abc');
    const { container } = render(SideRail);
    const active = container.querySelector('.rail-item.active') as HTMLAnchorElement;
    expect(active.getAttribute('href')).toBe('#/trips');
  });

  it('hides the inbox count when there is nothing unread', () => {
    stores.badge.set(0);
    const { container } = render(SideRail);
    expect(container.querySelector('.rail-badge')).toBeNull();
  });

  it('shows the inbox count when there is something unread', () => {
    stores.badge.set(3);
    const { container } = render(SideRail);
    expect(container.querySelector('.rail-badge')?.textContent).toBe('3');
    stores.badge.set(0);
  });
});

describe('TabBar', () => {
  // Both surfaces read the same NAV_ITEMS list, which is the point: the rail
  // and the dock cannot drift apart on order, labels or active-route rules.
  it('renders the same entries in the same order as the rail', () => {
    const { container } = render(TabBar);
    const hrefs = [...container.querySelectorAll('.tab-item')].map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(NAV_ITEMS.map((i) => i.href));
  });

  it('carries the shared .nav-item hook used to address either surface', () => {
    const { container } = render(TabBar);
    expect(container.querySelectorAll('.nav-item')).toHaveLength(NAV_ITEMS.length);
  });
});

describe('the project mark', () => {
  // The one place the app names itself, so it points at the project.
  it('links to the repository in a new tab, safely', () => {
    const { container } = render(SideRail);
    const mark = container.querySelector('.rail-mark') as HTMLAnchorElement;

    expect(mark.tagName).toBe('A');
    expect(mark.getAttribute('href')).toBe('https://github.com/thiagodsti/partiu');
    expect(mark.getAttribute('target')).toBe('_blank');
    // noreferrer as well as noopener: the target is a third-party host.
    expect(mark.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('is labelled, since "P" says nothing to a screen reader', () => {
    const { container } = render(SideRail);
    expect(container.querySelector('.rail-mark')?.getAttribute('aria-label')).toBeTruthy();
  });
});
