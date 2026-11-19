import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  installViewTransitions,
  interceptableHref,
  navDirection,
  notifyRouteLoaded,
  routePath,
} from './viewTransition';

describe('routePath', () => {
  it('drops the hash and the query string', () => {
    expect(routePath('#/trips/4?tab=docs')).toBe('/trips/4');
  });

  it('reads an empty hash as the root', () => {
    expect(routePath('')).toBe('/');
    expect(routePath('#')).toBe('/');
  });
});

describe('navDirection', () => {
  it('is a push when going deeper into the same section', () => {
    expect(navDirection('/trips', '/trips/4')).toBe('forward');
    expect(navDirection('/trips/4', '/trips/4/flights/9')).toBe('forward');
    expect(navDirection('/history', '/history/4')).toBe('forward');
  });

  it('is a pop when coming back out', () => {
    expect(navDirection('/trips/4/flights/9', '/trips/4')).toBe('back');
    expect(navDirection('/trips/4', '/trips')).toBe('back');
  });

  it('treats the root as the trips list', () => {
    expect(navDirection('/', '/trips/4')).toBe('forward');
    expect(navDirection('/trips/4', '/')).toBe('back');
  });

  it('cross-fades between sections and between peers', () => {
    expect(navDirection('/trips', '/stats')).toBe('fade');
    expect(navDirection('/trips/4', '/settings')).toBe('fade');
    expect(navDirection('/trips/4', '/trips/5')).toBe('fade');
  });
});

function clickOn(el: Element, init: MouseEventInit = {}): MouseEvent {
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init });
  el.dispatchEvent(event);
  return event;
}

describe('interceptableHref', () => {
  let anchor: HTMLAnchorElement;

  beforeEach(() => {
    window.location.hash = '#/trips';
    anchor = document.createElement('a');
    anchor.setAttribute('href', '#/trips/4');
    anchor.innerHTML = '<span>Lisbon</span>';
    document.body.appendChild(anchor);
  });

  afterEach(() => {
    anchor.remove();
  });

  // Built rather than dispatched: happy-dom follows a link while the click is
  // still bubbling through it, so by the time a document listener runs the
  // hash has already changed — a browser only navigates after dispatch.
  function hrefFor(target: Element, init: MouseEventInit = {}, prevented = false): string | null {
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init });
    Object.defineProperty(event, 'target', { value: target });
    if (prevented) event.preventDefault();
    return interceptableHref(event);
  }

  it('takes a plain click on an in-app link, from inside it too', () => {
    expect(hrefFor(anchor.querySelector('span')!)).toBe('#/trips/4');
  });

  it('leaves modified and non-primary clicks to the browser', () => {
    expect(hrefFor(anchor, { metaKey: true })).toBeNull();
    expect(hrefFor(anchor, { ctrlKey: true })).toBeNull();
    expect(hrefFor(anchor, { button: 1 })).toBeNull();
  });

  it('leaves external, new-tab and download links alone', () => {
    anchor.setAttribute('href', 'https://example.com');
    expect(hrefFor(anchor)).toBeNull();
    anchor.setAttribute('href', '#/trips/4');
    anchor.target = '_blank';
    expect(hrefFor(anchor)).toBeNull();
    anchor.removeAttribute('target');
    anchor.setAttribute('download', '');
    expect(hrefFor(anchor)).toBeNull();
  });

  it('does nothing for a link to the page already open', () => {
    anchor.setAttribute('href', '#/trips');
    expect(hrefFor(anchor)).toBeNull();
  });

  it('respects a component that already handled the click', () => {
    expect(hrefFor(anchor, {}, true)).toBeNull();
  });
});

describe('installViewTransitions', () => {
  let anchor: HTMLAnchorElement;
  let uninstall: () => void = () => {};

  beforeEach(() => {
    window.location.hash = '#/trips';
    anchor = document.createElement('a');
    anchor.setAttribute('href', '#/trips/4');
    document.body.appendChild(anchor);
  });

  afterEach(() => {
    uninstall();
    anchor.remove();
    vi.unstubAllGlobals();
    // @ts-expect-error — test-only removal of the stub
    delete document.startViewTransition;
  });

  it('leaves navigation untouched where the API is missing', () => {
    uninstall = installViewTransitions();
    const event = clickOn(anchor);
    expect(event.defaultPrevented).toBe(false);
  });

  it('does not animate for readers who asked for reduced motion', () => {
    const start = vi.fn();
    document.startViewTransition = start as unknown as typeof document.startViewTransition;
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce') }));
    uninstall = installViewTransitions();
    const event = clickOn(anchor);
    expect(event.defaultPrevented).toBe(false);
    expect(start).not.toHaveBeenCalled();
  });

  it('navigates inside a transition and waits for the route to load', async () => {
    let update: (() => Promise<void>) | undefined;
    let finish!: () => void;
    const finished = new Promise<void>((r) => (finish = r));
    document.startViewTransition = ((cb: () => Promise<void>) => {
      update = cb;
      return { finished };
    }) as unknown as typeof document.startViewTransition;
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    uninstall = installViewTransitions();

    const event = clickOn(anchor);
    expect(event.defaultPrevented).toBe(true);
    expect(document.documentElement.dataset.navDirection).toBe('forward');

    let settled = false;
    const running = update!().then(() => (settled = true));
    expect(window.location.hash).toBe('#/trips/4');
    await Promise.resolve();
    expect(settled).toBe(false);
    notifyRouteLoaded();
    await running;
    expect(settled).toBe(true);

    finish();
    await finished;
    await Promise.resolve();
    expect(document.documentElement.dataset.navDirection).toBeUndefined();
  });

  it('gives up waiting on a route that never reports itself loaded', async () => {
    vi.useFakeTimers();
    let update: (() => Promise<void>) | undefined;
    document.startViewTransition = ((cb: () => Promise<void>) => {
      update = cb;
      return { finished: new Promise(() => {}) };
    }) as unknown as typeof document.startViewTransition;
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    uninstall = installViewTransitions();

    clickOn(anchor);
    const running = update!();
    await vi.advanceTimersByTimeAsync(400);
    await expect(running).resolves.toBeUndefined();
    vi.useRealTimers();
  });
});
