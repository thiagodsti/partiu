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

  // Country name → ISO 2-letter code (lowercase). Lets users type "italy" and
  // match country_code "it" stored in the search_index.
  const COUNTRY_CODES: Record<string, string> = {
    "afghanistan":"af","albania":"al","algeria":"dz","angola":"ao","argentina":"ar",
    "armenia":"am","australia":"au","austria":"at","azerbaijan":"az","bahrain":"bh",
    "bangladesh":"bd","belarus":"by","belgium":"be","bolivia":"bo","bosnia":"ba",
    "botswana":"bw","brazil":"br","brasil":"br","bulgaria":"bg","cambodia":"kh",
    "cameroon":"cm","canada":"ca","chile":"cl","china":"cn","colombia":"co",
    "costa rica":"cr","croatia":"hr","cuba":"cu","cyprus":"cy","czech":"cz",
    "czechia":"cz","denmark":"dk","dominican republic":"do","ecuador":"ec",
    "egypt":"eg","el salvador":"sv","ethiopia":"et","finland":"fi","france":"fr",
    "georgia":"ge","germany":"de","ghana":"gh","greece":"gr","guatemala":"gt",
    "haiti":"ht","honduras":"hn","hungary":"hu","iceland":"is","india":"in",
    "indonesia":"id","iran":"ir","iraq":"iq","ireland":"ie","israel":"il",
    "italy":"it","jamaica":"jm","japan":"jp","jordan":"jo","kazakhstan":"kz",
    "kenya":"ke","kuwait":"kw","latvia":"lv","lebanon":"lb","libya":"ly",
    "lithuania":"lt","luxembourg":"lu","malaysia":"my","maldives":"mv","malta":"mt",
    "mauritius":"mu","mexico":"mx","moldova":"md","montenegro":"me","morocco":"ma",
    "mozambique":"mz","myanmar":"mm","namibia":"na","nepal":"np","netherlands":"nl",
    "new zealand":"nz","nicaragua":"ni","nigeria":"ng","norway":"no","oman":"om",
    "pakistan":"pk","panama":"pa","paraguay":"py","peru":"pe","philippines":"ph",
    "poland":"pl","portugal":"pt","qatar":"qa","romania":"ro","russia":"ru",
    "rwanda":"rw","saudi arabia":"sa","senegal":"sn","serbia":"rs","singapore":"sg",
    "slovakia":"sk","slovenia":"si","somalia":"so","south africa":"za",
    "south korea":"kr","spain":"es","sri lanka":"lk","sudan":"sd","sweden":"se",
    "switzerland":"ch","syria":"sy","taiwan":"tw","tanzania":"tz","thailand":"th",
    "tunisia":"tn","turkey":"tr","turkiye":"tr","uganda":"ug","ukraine":"ua",
    "united arab emirates":"ae","uae":"ae","emirates":"ae","united kingdom":"gb",
    "uk":"gb","britain":"gb","england":"gb","united states":"us","usa":"us",
    "america":"us","uruguay":"uy","uzbekistan":"uz","venezuela":"ve","vietnam":"vn",
    "zimbabwe":"zw",
  };

  let loading = $state(true);
  let error = $state<string | null>(null);
  let allTrips = $state<Trip[]>([]);
  let immichConfigured = $state(false);
  let immichBaseUrl = $state('');
  let query = $state('');

  async function load() {
    loading = true;
    error = null;
    try {
      const [data, s] = await Promise.all([
        tripsApi.list(),
        settingsApi.get().catch(() => null),
      ]);
      allTrips = data?.trips ?? [];
      immichConfigured = !!(s?.immich_url && s?.immich_api_key_set);
      immichBaseUrl = s?.immich_url?.replace(/\/$/, '') ?? '';
    } catch (err) {
      error = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  function norm(s: string): string {
    return s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
  }

  function matchesSearch(trip: Trip, q: string): boolean {
    const needle = norm(q.trim());
    const cc = COUNTRY_CODES[needle];
    const index = trip.search_index ?? norm(trip.name);
    if (cc !== undefined) {
      const tokens = index.split(/\s+/);
      if (tokens.includes(cc)) return true;
    }
    return index.includes(needle);
  }

  const completedTrips = $derived(
    allTrips.filter((t) => inferTripStatus(t) === "completed").slice().reverse()
  );

  const filtered = $derived(
    query.trim() === '' ? completedTrips : completedTrips.filter((t) => matchesSearch(t, query))
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
    <div class="search-bar">
      <input
        class="form-input search-input"
        type="search"
        placeholder={$t('history.search_placeholder')}
        bind:value={query}
      />
    </div>

    {#if filtered.length === 0}
      <EmptyState
        title={$t('history.no_results')}
        description={$t('history.no_results_desc')}
      />
    {:else}
      {#each filtered as trip (trip.id)}
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
                  allTrips = allTrips.map((t) =>
                    t.id === trip.id ? { ...t, immich_album_id: albumId } : t
                  );
                }}
              />
            {/if}
          {/snippet}
        </TripCard>
      {/each}
    {/if}
  {/if}
</div>

<style>
  .search-bar {
    padding: var(--space-sm) var(--space-md);
    position: sticky;
    top: 56px;
    background: var(--bg);
    z-index: 10;
  }
</style>
