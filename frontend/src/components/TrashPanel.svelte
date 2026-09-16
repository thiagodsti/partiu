<script lang="ts">
  import { onMount } from 'svelte';
  import { trashApi } from '../api/client';
  import type { TrashItem, RestoreResult } from '../api/types';
  import { formatDayMonth } from '../lib/utils';
  import { t } from '../lib/i18n';

  let items = $state<TrashItem[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let busyId = $state<number | null>(null);
  let lastRestore = $state<RestoreResult | null>(null);

  export async function reload() {
    loading = true;
    error = null;
    try {
      items = await trashApi.list();
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      loading = false;
    }
  }

  async function restore(item: TrashItem) {
    busyId = item.id;
    try {
      lastRestore = await trashApi.restore(item.id);
      items = items.filter((i) => i.id !== item.id);
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      busyId = null;
    }
  }

  async function purge(item: TrashItem) {
    if (!confirm($t('trash.purge_confirm', { values: { label: item.label } }))) return;
    busyId = item.id;
    try {
      await trashApi.purge(item.id);
      items = items.filter((i) => i.id !== item.id);
    } catch (err) {
      error = (err as Error)?.message ?? String(err);
    } finally {
      busyId = null;
    }
  }

  function describe(item: TrashItem): string {
    const s = item.summary;
    if (item.kind === 'flight') {
      return s.departure_datetime ? formatDayMonth(s.departure_datetime) : '';
    }
    const parts: string[] = [];
    if (s.start_date && s.end_date) parts.push(`${formatDayMonth(s.start_date)} – ${formatDayMonth(s.end_date)}`);
    if (s.flight_count) parts.push($t('trash.n_flights', { values: { n: s.flight_count } }));
    if (s.stay_count) parts.push($t('trash.n_stays', { values: { n: s.stay_count } }));
    if (s.expense_count) parts.push($t('trash.n_expenses', { values: { n: s.expense_count } }));
    if (s.rating) parts.push(`★ ${s.rating}`);
    return parts.join(' · ');
  }

  function skippedSummary(r: RestoreResult): string {
    const total = Object.values(r.skipped).reduce((a, b) => a + b, 0);
    return total ? $t('trash.restored_with_skips', { values: { label: r.label, n: total } }) : $t('trash.restored', { values: { label: r.label } });
  }

  onMount(() => {
    void reload();
  });
</script>

<div class="settings-section trash-panel">
  <div class="settings-section-title">{$t('trash.title')}</div>
  <p class="text-muted trash-desc">{$t('trash.desc')}</p>

  {#if lastRestore}
    <p class="trash-notice" role="status">{skippedSummary(lastRestore)}</p>
  {/if}
  {#if error}
    <p class="trash-error" role="alert">{error}</p>
  {/if}

  {#if loading}
    <p class="text-muted">{$t('trash.loading')}</p>
  {:else if items.length === 0}
    <p class="text-muted">{$t('trash.empty')}</p>
  {:else}
    <ul class="trash-list">
      {#each items as item (item.id)}
        <li class="trash-item">
          <div class="trash-main">
            <span class="trash-kind">{item.kind === 'trip' ? $t('trash.kind_trip') : $t('trash.kind_flight')}</span>
            <span class="trash-label">{item.label}</span>
            <span class="text-muted trash-meta">{describe(item)}</span>
            <span class="text-muted trash-meta">{$t('trash.deleted_on', { values: { date: formatDayMonth(item.deleted_at) } })}</span>
          </div>
          <div class="trash-actions">
            <button class="btn btn-secondary btn-sm" disabled={busyId === item.id} onclick={() => restore(item)}>
              {$t('trash.restore')}
            </button>
            <button class="btn btn-danger btn-sm" disabled={busyId === item.id} onclick={() => purge(item)}>
              {$t('trash.purge')}
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .trash-desc { margin: 0 0 var(--space-md); font-size: 0.875rem; }
  .trash-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-sm); }
  .trash-item {
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
    gap: var(--space-sm); padding: var(--space-sm) 0; border-top: 1px solid var(--border);
  }
  .trash-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 220px; }
  .trash-kind { font-size: 0.75rem; color: var(--text-muted); }
  .trash-label { font-weight: 600; overflow-wrap: anywhere; }
  .trash-meta { font-size: 0.8rem; }
  .trash-actions { display: flex; gap: var(--space-xs); flex-wrap: wrap; }
  .trash-notice { font-size: 0.875rem; margin: 0 0 var(--space-sm); }
  .trash-error { color: var(--danger-text); font-size: 0.875rem; margin: 0 0 var(--space-sm); }
</style>
