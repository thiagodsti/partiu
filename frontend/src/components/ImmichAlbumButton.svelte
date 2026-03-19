<script lang="ts">
  import { tripsApi } from '../api/client';
  import { t } from '../lib/i18n';

  interface Props {
    tripId: string;
    immichAlbumId: string | null | undefined;
    immichBaseUrl: string;
    onAlbumCreated?: (albumId: string) => void;
    style?: string;
  }

  let { tripId, immichAlbumId, immichBaseUrl, onAlbumCreated, style }: Props = $props();

  let creating = $state(false);
  let error = $state<string | null>(null);

  function openAlbum(albumId: string) {
    const deepLink = `immich:///albums/${albumId}`;
    const webUrl = `${immichBaseUrl}/albums/${albumId}`;

    let appOpened = false;

    const onVisibilityChange = () => {
      if (document.hidden) {
        appOpened = true;
        document.removeEventListener('visibilitychange', onVisibilityChange);
        clearTimeout(fallbackTimer);
      }
    };

    document.addEventListener('visibilitychange', onVisibilityChange);

    const fallbackTimer = setTimeout(() => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (!appOpened) {
        window.open(webUrl, '_blank', 'noopener');
      }
    }, 1500);

    window.location.href = deepLink;
  }

  async function handleClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();

    if (immichAlbumId) {
      openAlbum(immichAlbumId);
      return;
    }

    creating = true;
    error = null;
    try {
      const result = await tripsApi.createImmichAlbum(tripId);
      onAlbumCreated?.(result.album_id);
      openAlbum(result.album_id);
    } catch (err) {
      error = (err as Error).message;
    } finally {
      creating = false;
    }
  }
</script>

<div class="immich-album-btn-wrap">
  <button class="btn btn-secondary" {style} disabled={creating} onclick={handleClick}>
    {#if creating}
      {$t('immich.creating_album')}
    {:else if immichAlbumId}
      {$t('immich.open_album')}
    {:else}
      {$t('immich.create_album')}
    {/if}
  </button>
  {#if error}
    <p class="immich-album-error">{error}</p>
  {/if}
</div>

<style>
  .immich-album-btn-wrap {
    display: contents;
  }

  .immich-album-error {
    font-size: 0.75rem;
    color: var(--danger);
    margin-top: var(--space-xs);
    margin-bottom: 0;
  }
</style>
