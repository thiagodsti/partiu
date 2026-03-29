<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { SyncStatus } from '../api/types';
  import { formatDateTimeLocale } from '../lib/utils';
  import { t } from '../lib/i18n';

  interface Props {
    syncStatus: SyncStatus | null;
    /** Extra elements rendered on the right (e.g. action buttons) */
    children?: Snippet;
    id?: string;
    style?: string;
  }

  const { syncStatus, children, id, style }: Props = $props();

  const syncRunning = $derived(syncStatus?.status === 'running');
  const syncHasError = $derived(syncStatus?.status === 'error');
  const lastSynced = $derived(syncStatus?.last_synced_at);

  const nextSyncLabel = $derived.by(() => {
    if (!syncStatus?.last_synced_at || !syncStatus?.sync_interval_minutes) return null;
    const nextMs =
      new Date(syncStatus.last_synced_at).getTime() +
      syncStatus.sync_interval_minutes * 60 * 1000;
    const nowMs = Date.now();
    if (nextMs <= nowMs) return $t('sync.any_moment');
    const diffMin = Math.round((nextMs - nowMs) / 60000);
    if (diffMin < 1) return $t('sync.any_moment');
    const h = Math.floor(diffMin / 60);
    const m = diffMin % 60;
    const rel = h > 0 ? `${h}h ${m}m` : `${m}m`;
    const absTime = new Date(nextMs).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
    return $t('sync.next_at', { values: { rel, absTime } });
  });
</script>

<div class="sync-status-bar" {id} {style}>
  <span
    class="sync-dot {syncRunning ? 'running' : syncHasError ? 'error' : 'idle'}"
  ></span>
  <span class="sync-text">
    {#if syncRunning}
      {#if syncStatus?.emails_total && syncStatus.emails_total > 0}
        {$t('sync.running_progress', { values: { processed: syncStatus.emails_processed ?? 0, total: syncStatus.emails_total } })}
      {:else}
        {$t('sync.running')}
      {/if}
    {:else if syncHasError}
      {$t('sync.error')}: {syncStatus?.last_error ?? ''}
    {:else if lastSynced}
      {$t('sync.last_sync', { values: { time: formatDateTimeLocale(lastSynced) } })}
      {#if nextSyncLabel}<span style="opacity:0.6"
          >{$t('sync.next_sync', { values: { label: nextSyncLabel } })}</span
        >{/if}
    {:else}
      {$t('sync.never')}
    {/if}
  </span>
  {#if children}<div class="sync-actions">{@render children()}</div>{/if}
</div>
