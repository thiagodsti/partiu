<script lang="ts">
  import { onMount } from 'svelte';
  import Router from 'svelte-spa-router';
  import TabBar from './components/TabBar.svelte';
  import TripsListPage from './pages/TripsListPage.svelte';
  import TripDetailPage from './pages/TripDetailPage.svelte';
  import FlightDetailPage from './pages/FlightDetailPage.svelte';
  import SettingsPage from './pages/SettingsPage.svelte';
  import HistoryPage from './pages/HistoryPage.svelte';
  import LoginPage from './pages/LoginPage.svelte';
  import SetupPage from './pages/SetupPage.svelte';
  import UsersPage from './pages/UsersPage.svelte';
  import AddFlightPage from './pages/AddFlightPage.svelte';
  import AddTripPage from './pages/AddTripPage.svelte';
  import EditTripPage from './pages/EditTripPage.svelte';
  import StatsPage from './pages/StatsPage.svelte';
  import { authApi } from './api/client';
  import { currentUser, authLoading } from './lib/authStore';
  import ToastContainer from './components/ToastContainer.svelte';

  const routes = {
    '/': TripsListPage,
    '/trips': TripsListPage,
    '/trips/new': AddTripPage,
    '/trips/:id/edit': EditTripPage,
    '/trips/:id': TripDetailPage,
    '/trips/:tripId/flights/:flightId': FlightDetailPage,
    '/trips/:tripId/add-flight': AddFlightPage,
    '/stats': StatsPage,
    '/history': HistoryPage,
    '/history/:id': TripDetailPage,
    '/history/:tripId/flights/:flightId': FlightDetailPage,
    '/settings': SettingsPage,
    '/admin/users': UsersPage,
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
    // Track hash changes to hide TabBar on auth pages
    const onHashChange = () => {
      currentHash = window.location.hash.replace('#', '') || '/';
    };
    window.addEventListener('hashchange', onHashChange);

    // Auth check runs async but cleanup is returned synchronously
    (async () => {
      try {
        const user = await authApi.me();
        currentUser.set(user);
        authLoading.set(false);

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

    return () => {
      window.removeEventListener('hashchange', onHashChange);
    };
  });
</script>

{#if $authLoading}
  <!-- Blank while checking auth to avoid flash -->
  <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;color:var(--text-muted);">
    Loading...
  </div>
{:else}
  <svelte:boundary>
    <Router {routes} on:routeEvent={routeNotFound} />
    {#if showTabBar}
      <TabBar />
    {/if}
    <ToastContainer />
    {#snippet failed()}
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;gap:1rem;padding:2rem;text-align:center;">
        <p style="color:var(--text-muted);font-size:1.1rem;">Something went wrong.</p>
        <button onclick={() => window.location.reload()}
                style="padding:0.5rem 1.25rem;border-radius:6px;border:none;background:var(--accent,#6366f1);color:#fff;cursor:pointer;font-size:1rem;">
          Reload
        </button>
      </div>
    {/snippet}
  </svelte:boundary>
{/if}
