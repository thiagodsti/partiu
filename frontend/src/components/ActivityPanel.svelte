<script lang="ts">
  import { onMount } from 'svelte';
  import { activityApi } from '../api/client';
  import type { ActivityEntry } from '../api/types';
  import { formatDayMonth, formatTime } from '../lib/utils';
  import { t } from '../lib/i18n';

  let entries = $state<ActivityEntry[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  export async function reload() {
    loading = true;
    error = null;
    try {
      entries = await activityApi.list(100);
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      loading = false;
    }
  }

  const KNOWN = new Set([
    'trip.trashed', 'trip.restored', 'trip.purged',
    'flight.trashed', 'flight.restored', 'flight.purged',
    'trips.merged', 'trips.regrouped', 'sync.full', 'sync.rescan',
  ]);

  function describe(e: ActivityEntry): string {
    const key = KNOWN.has(e.action) ? `activity.${e.action.replace('.', '_')}` : 'activity.unknown';
    const d = e.details ?? {};
    return $t(key, {
      values: {
        label: e.label ?? '',
        action: e.action,
        source: (d.source_name as string) ?? '',
        from: (d.from_version as string) ?? '',
        to: (d.to_version as string) ?? '',
        since: (d.since as string) ?? '',
      },
    });
  }

  onMount(() => {
    void reload();
  });
</script>

<div class="settings-section activity-panel">
  <div class="settings-section-title">{$t('activity.title')}</div>
  <p class="text-muted activity-desc">{$t('activity.desc')}</p>
  {#if error}
    <p class="activity-error" role="alert">{error}</p>
  {:else if loading}
    <p class="text-muted">{$t('activity.loading')}</p>
  {:else if entries.length === 0}
    <p class="text-muted">{$t('activity.empty')}</p>
  {:else}
    <ul class="activity-list">
      {#each entries as e (e.id)}
        <li class="activity-item">
          <span class="activity-when text-muted">{formatDayMonth(e.created_at)} {formatTime(e.created_at)}</span>
          <span class="activity-what">{describe(e)}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .activity-desc { margin: 0 0 var(--space-md); font-size: 0.875rem; }
  .activity-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-xs); max-height: 24rem; overflow-y: auto; }
  .activity-item { display: flex; gap: var(--space-sm); font-size: 0.875rem; padding: 4px 0; border-top: 1px solid var(--border); flex-wrap: wrap; }
  .activity-when { flex: 0 0 auto; font-variant-numeric: tabular-nums; }
  .activity-what { flex: 1 1 200px; overflow-wrap: anywhere; }
  .activity-error { color: var(--danger-text); font-size: 0.875rem; }
</style>
