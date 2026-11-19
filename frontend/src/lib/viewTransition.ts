// Page transitions for in-app navigation, through the View Transitions API.
//
// svelte-spa-router swaps the page on `hashchange`, which is too late to wrap:
// by the time anything hears that event the URL has changed and the router is
// already re-rendering, so the "old" snapshot would be the new page. The only
// point early enough is the click itself, so this listens for clicks on
// in-app links, cancels the browser's own navigation, and performs it inside
// `document.startViewTransition`. Browsers without the API, reduced-motion
// readers and programmatic navigation (`location.hash = …`, the browser's back
// button) all get the plain swap they always had — this only ever adds motion.

export type NavDirection = 'forward' | 'back' | 'fade';

// How long the frozen old frame may wait for the new page to report itself
// loaded. Lazily-loaded routes need the chunk; everything else answers within a
// frame. Past this the transition runs on whatever has rendered, so a slow
// network can cost at most this much stillness.
const ROUTE_WAIT_MS = 350;

/** Strip `#` and any query string: `#/trips/4?x=1` → `/trips/4`. */
export function routePath(hash: string): string {
  const path = hash.replace(/^#/, '').split('?')[0];
  return path === '' ? '/' : path;
}

function segments(path: string): string[] {
  const parts = path.split('/').filter(Boolean);
  // `/` is the trips list under another name.
  return parts.length === 0 ? ['trips'] : parts;
}

/**
 * Which way a navigation moves. Deeper into the same section is a push
 * ("forward"), back out of it is a pop ("back"), and anything else — a tab
 * switch, a jump between sections — is a cross-fade, because sliding sideways
 * between peers would claim a hierarchy that is not there.
 */
export function navDirection(from: string, to: string): NavDirection {
  const a = segments(from);
  const b = segments(to);
  if (a[0] !== b[0]) return 'fade';
  if (b.length > a.length) return 'forward';
  if (b.length < a.length) return 'back';
  return 'fade';
}

let routeLoadedWaiters: Array<() => void> = [];

/** Called from the Router's `routeLoaded` event in App.svelte. */
export function notifyRouteLoaded(): void {
  const waiters = routeLoadedWaiters;
  routeLoadedWaiters = [];
  for (const resolve of waiters) resolve();
}

function nextRouteLoaded(timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, timeoutMs);
    function done() {
      clearTimeout(timer);
      routeLoadedWaiters = routeLoadedWaiters.filter((w) => w !== done);
      resolve();
    }
    routeLoadedWaiters.push(done);
  });
}

function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/** The in-app hash a click should navigate to, or null to leave it alone. */
export function interceptableHref(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const target = event.target as Element | null;
  const anchor = target?.closest?.('a');
  if (!anchor) return null;
  if (anchor.target && anchor.target !== '_self') return null;
  if (anchor.hasAttribute('download')) return null;
  const href = anchor.getAttribute('href') ?? '';
  if (!href.startsWith('#/')) return null;
  if (href === window.location.hash) return null;
  return href;
}

let transitionGeneration = 0;

function onClick(event: MouseEvent): void {
  const href = interceptableHref(event);
  if (href === null) return;

  event.preventDefault();
  const root = document.documentElement;
  const direction = navDirection(routePath(window.location.hash), routePath(href));
  root.dataset.navDirection = direction;
  // A second click before this transition ends starts a new one, which skips
  // this one and fires its `finished` — so only the transition that still owns
  // the attribute may clear it, or the newer one loses its slide halfway in.
  const generation = ++transitionGeneration;

  const transition = document.startViewTransition(async () => {
    const loaded = nextRouteLoaded(ROUTE_WAIT_MS);
    window.location.hash = href;
    await loaded;
  });
  transition.finished.finally(() => {
    if (generation === transitionGeneration) delete root.dataset.navDirection;
  });
}

/** Install the click listener. Returns a function that removes it. */
export function installViewTransitions(): () => void {
  if (typeof document.startViewTransition !== 'function' || reducedMotion()) {
    return () => {};
  }
  // Bubble phase on the document, so a component that handles its own link
  // click and calls preventDefault() has already had its say.
  document.addEventListener('click', onClick);
  return () => document.removeEventListener('click', onClick);
}
