<script lang="ts">
  import Router from 'svelte-spa-router';
  import { wrap } from 'svelte-spa-router/wrap';
  import TabBar from './components/TabBar.svelte';
  import TripsListPage from './pages/TripsListPage.svelte';
  import TripDetailPage from './pages/TripDetailPage.svelte';
  import FlightDetailPage from './pages/FlightDetailPage.svelte';
  import SettingsPage from './pages/SettingsPage.svelte';
  import HistoryPage from './pages/HistoryPage.svelte';

  const routes = {
    '/': TripsListPage,
    '/trips': TripsListPage,
    '/trips/:id': TripDetailPage,
    '/trips/:tripId/flights/:flightId': FlightDetailPage,
    '/history': HistoryPage,
    '/settings': SettingsPage,
  };

  function routeNotFound() {
    window.location.hash = '/trips';
  }
</script>

<Router {routes} on:routeEvent={routeNotFound} />
<TabBar />
