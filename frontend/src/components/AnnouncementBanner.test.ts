import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import AnnouncementBanner from './AnnouncementBanner.svelte';
import type { User } from '../api/types';

// Hand-rolled rather than `writable`: vi.hoisted runs before any import, so
// nothing from svelte/store is available to it yet.
const { userStore } = vi.hoisted(() => {
  let value: unknown = null;
  const subs = new Set<(v: unknown) => void>();
  return {
    userStore: {
      subscribe(fn: (v: unknown) => void) {
        subs.add(fn);
        fn(value);
        return () => subs.delete(fn);
      },
      set(v: unknown) {
        value = v;
        subs.forEach((fn) => fn(value));
      },
    },
  };
});

const setUser = (u: Partial<User> | null) => userStore.set(u);

vi.mock('../lib/authStore', () => ({ currentUser: userStore }));

vi.mock('../lib/i18n', () => ({
  t: {
    subscribe: (fn: (v: (k: string) => string) => void) => {
      fn((k: string) => k);
      return () => {};
    },
  },
}));

describe('AnnouncementBanner', () => {
  beforeEach(() => {
    sessionStorage.clear();
    setUser(null);
  });

  it('renders nothing without an announcement', () => {
    setUser({ id: '1', username: 'admin' });
    const { container } = render(AnnouncementBanner);
    expect(container.querySelector('.announcement-banner')).toBeNull();
  });

  it('shows the announcement with a dismiss button on an ordinary install', () => {
    setUser({ id: '1', username: 'admin', announcement: 'Maintenance Sunday' });
    const { container } = render(AnnouncementBanner);
    expect(container.querySelector('.announcement-banner span')!.textContent).toBe(
      'Maintenance Sunday',
    );
    expect(container.querySelector('.announcement-banner button')).toBeInTheDocument();
  });

  it('respects a dismissal of that same announcement', () => {
    sessionStorage.setItem('announcement_dismissed', 'Maintenance Sunday');
    setUser({ id: '1', username: 'admin', announcement: 'Maintenance Sunday' });
    const { container } = render(AnnouncementBanner);
    expect(container.querySelector('.announcement-banner')).toBeNull();
  });

  describe('on a demo instance', () => {
    it('banners the shared-account notice with no announcement configured', () => {
      setUser({ id: '1', username: 'demo', demo: true });
      const { container } = render(AnnouncementBanner);
      expect(container.querySelector('.announcement-banner span')!.textContent).toBe('demo.banner');
    });

    // A fact about the install is not a notice: dismissing it would hide from
    // the next visitor that they are sharing an account with everyone.
    it('offers no dismiss button', () => {
      setUser({ id: '1', username: 'demo', demo: true });
      const { container } = render(AnnouncementBanner);
      expect(container.querySelector('.announcement-banner button')).toBeNull();
    });

    it('stays up even when this announcement was dismissed before', () => {
      sessionStorage.setItem('announcement_dismissed', 'Shared demo');
      setUser({ id: '1', username: 'demo', demo: true, announcement: 'Shared demo' });
      const { container } = render(AnnouncementBanner);
      expect(container.querySelector('.announcement-banner span')!.textContent).toBe('Shared demo');
    });

    it("prefers the deployer's own announcement over the default text", () => {
      setUser({ id: '1', username: 'demo', demo: true, announcement: 'Resets nightly' });
      const { container } = render(AnnouncementBanner);
      expect(container.querySelector('.announcement-banner span')!.textContent).toBe(
        'Resets nightly',
      );
    });
  });
});
