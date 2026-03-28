<script lang="ts">
  import { tripsApi, settingsApi } from "../api/client";
  import type { Trip } from "../api/types";
  import { tripImageBust } from "../lib/tripImageStore";
  import { inferTripStatus } from "../lib/utils";
  import LoadingScreen from "../components/LoadingScreen.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import TopNav from "../components/TopNav.svelte";
  import TripCard from "../components/TripCard.svelte";
  import ImmichAlbumButton from "../components/ImmichAlbumButton.svelte";
  import { t } from "../lib/i18n";
  import { ImageRefreshManager } from "../lib/imageRefresh.svelte";

  let loading = $state(true);
  let error = $state<string | null>(null);
  let tripsList = $state<Trip[]>([]);
  let immichConfigured = $state(false);
  let immichBaseUrl = $state('');

  async function load() {
    loading = true;
    error = null;
    try {
      const [data, s] = await Promise.all([
        tripsApi.list(),
        settingsApi.get().catch(() => null),
      ]);
      tripsList = data?.trips ?? [];
      immichConfigured = !!(s?.immich_url && s?.immich_api_key_set);
      immichBaseUrl = s?.immich_url?.replace(/\/$/, '') ?? '';
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  const completedTrips = $derived(
    tripsList.filter((t) => inferTripStatus(t) === "completed").slice().reverse(),
  );

  // ---- Image refresh ----
  const imgRefresh = new ImageRefreshManager();
</script>

<TopNav title={$t('history.title')} />

<div class="main-content">
  {#if loading}
    <LoadingScreen message={$t('history.loading')} />
  {:else if error}
    <EmptyState icon="⚠️" title={$t('history.load_error')} description={error}>
      <button class="btn btn-primary" onclick={() => load()}>{$t('history.retry')}</button>
    </EmptyState>
  {:else if completedTrips.length === 0}
    <EmptyState
      title={$t('history.empty_title')}
      description={$t('history.empty_desc')}
    />
  {:else}
    {#each completedTrips as trip (trip.id)}
      <TripCard
        {trip}
        href="#/history/{trip.id}"
        imageUrl={tripImageBust.urlFor(trip.id, $tripImageBust)}
        imgFailed={imgRefresh.imgFailed[trip.id] ?? false}
        refreshing={imgRefresh.refreshingId === trip.id}
        showStars
        onImageError={(e) => imgRefresh.handleError(e, trip.id)}
        onRefreshImage={(e) => imgRefresh.refresh(e, trip.id)}
      >
        {#snippet badge()}
          <span class="badge badge-completed">{$t('trips.completed')}</span>
        {/snippet}
        {#snippet footer()}
          {#if immichConfigured}
            <ImmichAlbumButton
              tripId={trip.id}
              immichAlbumId={trip.immich_album_id}
              {immichBaseUrl}
              style="margin-top:var(--space-sm);width:100%;font-size:0.8rem"
              onAlbumCreated={(albumId) => {
                tripsList = tripsList.map((t) =>
                  t.id === trip.id ? { ...t, immich_album_id: albumId } : t
                );
              }}
            />
          {/if}
        {/snippet}
      </TripCard>
    {/each}
  {/if}
</div>
