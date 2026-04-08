<script lang="ts">
  import { onMount } from 'svelte';
  import Router from 'svelte-spa-router';
  import wrap from 'svelte-spa-router/wrap';
  import TabBar from './components/TabBar.svelte';
  import TripsListPage from './pages/TripsListPage.svelte';
  import TripDetailPage from './pages/TripDetailPage.svelte';
  import LoginPage from './pages/LoginPage.svelte';
  import SetupPage from './pages/SetupPage.svelte';
  import { authApi, notificationsApi } from './api/client';
  import { currentUser, authLoading } from './lib/authStore';
  import { refreshInvitationCount } from './lib/invitationStore';
  import { applyUserLocale } from './lib/i18n';
  import ToastContainer from './components/ToastContainer.svelte';

  const routes = {
    '/': TripsListPage,
    '/trips': TripsListPage,
    '/trips/new': wrap({ asyncComponent: () => import('./pages/AddTripPage.svelte') }),
    '/trips/:id/edit': wrap({ asyncComponent: () => import('./pages/EditTripPage.svelte') }),
    '/trips/:id': TripDetailPage,
    '/trips/:tripId/flights/:flightId': wrap({ asyncComponent: () => import('./pages/FlightDetailPage.svelte') }),
    '/trips/:tripId/add-flight': wrap({ asyncComponent: () => import('./pages/AddFlightPage.svelte') }),
    '/stats': wrap({ asyncComponent: () => import('./pages/StatsPage.svelte') }),
    '/stats/map': wrap({ asyncComponent: () => import('./pages/WorldMapPage.svelte') }),
    '/history': wrap({ asyncComponent: () => import('./pages/HistoryPage.svelte') }),
    '/history/:id': TripDetailPage,
    '/history/:tripId/flights/:flightId': wrap({ asyncComponent: () => import('./pages/FlightDetailPage.svelte') }),
    '/settings': wrap({ asyncComponent: () => import('./pages/SettingsPage.svelte') }),
    '/admin/users': wrap({ asyncComponent: () => import('./pages/UsersPage.svelte') }),
    '/notifications': wrap({ asyncComponent: () => import('./pages/NotificationsPage.svelte') }),
    '/invitations': wrap({ asyncComponent: () => import('./pages/NotificationsPage.svelte') }),
    '/login': LoginPage,
    '/setup': SetupPage,
  };

  // Auth pages that should not show the TabBar
  const AUTH_ROUTES = new Set(['/login', '/setup']);

  let currentHash = $state(window.location.hash.replace('#', '') || '/');
  let showTabBar = $derived(!AUTH_ROUTES.has(currentHash));

  function routeNotFound() {
    window.location.hash = '/trips';
  }

  onMount(() => {
    // Track hash changes to hide TabBar on auth pages, and refresh invitation count on navigation
    const onHashChange = () => {
      currentHash = window.location.hash.replace('#', '') || '/';
      refreshInvitationCount();
    };
    window.addEventListener('hashchange', onHashChange);

    // Poll for invitations + unread notifications every 30 seconds while the tab is open
    const pollInterval = setInterval(refreshInvitationCount, 30_000);

    // Clear app badge when the user opens/returns to the app
    const clearBadge = () => {
      if (document.visibilityState === 'visible') {
        if ('clearAppBadge' in navigator) navigator.clearAppBadge().catch(() => {});
        notificationsApi.clearBadge().catch(() => {});
      }
    };
    document.addEventListener('visibilitychange', clearBadge);

    // Auth check runs async but cleanup is returned synchronously
    (async () => {
      try {
        const user = await authApi.me();
        currentUser.set(user);
        applyUserLocale(user.locale);
        authLoading.set(false);
        refreshInvitationCount();

        // Redirect away from auth pages if already logged in
        const hash = window.location.hash.replace('#', '');
        if (hash === '/login' || hash === '/setup' || hash === '') {
          window.location.hash = '/trips';
        }
      } catch (err: unknown) {
        authLoading.set(false);
        // Check if setup is required
        const raw = (err as Error)?.message ?? '';
        if (raw === 'setup_required') {
          window.location.hash = '/setup';
        } else {
          // 401 or other — redirect to login
          const hash = window.location.hash.replace('#', '');
          if (hash !== '/setup') {
            window.location.hash = '/login';
          }
        }
      }
    })();

    // Also clear immediately on load
    if ('clearAppBadge' in navigator) navigator.clearAppBadge().catch(() => {});
    notificationsApi.clearBadge().catch(() => {});

    // Silently restore push subscription if user previously opted in but subscription was lost
    import('./lib/notifications').then(({ restoreIfNeeded }) => restoreIfNeeded()).catch(() => {});;

    return () => {
      window.removeEventListener('hashchange', onHashChange);
      document.removeEventListener('visibilitychange', clearBadge);
      clearInterval(pollInterval);
    };
  });
</script>

{#if $authLoading}
  <!-- Blank while checking auth to avoid flash -->
  <div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);">
    Loading...
  </div>
{:else}
  <div class="app-shell">
    <svelte:boundary>
      <div class="app-content">
        <Router {routes} on:routeEvent={routeNotFound} />
      </div>
      {#if showTabBar}
        <TabBar />
      {/if}
      <ToastContainer />
      {#snippet failed()}
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1rem;padding:2rem;text-align:center;">
          <p style="color:var(--text-muted);font-size:1.1rem;">Something went wrong.</p>
          <button onclick={() => window.location.reload()}
                  style="padding:0.5rem 1.25rem;border-radius:6px;border:none;background:var(--accent,#6366f1);color:#fff;cursor:pointer;font-size:1rem;">
            Reload
          </button>
        </div>
      {/snippet}
    </svelte:boundary>
  </div>
{/if}
