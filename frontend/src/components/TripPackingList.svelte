<script lang="ts">
  import { packingApi } from '../api/client';
  import type { PackingItem } from '../api/types';
  import { t } from '../lib/i18n';

  interface Props {
    tripId: string;
  }

  const { tripId }: Props = $props();

  let items = $state<PackingItem[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);

  let newText = $state('');
  let adding = $state(false);

  let editingId = $state<string | null>(null);
  let editText = $state('');
  let editSaving = $state(false);

  const checkedCount = $derived(items.filter((i) => i.checked).length);
  const hasChecked = $derived(checkedCount > 0);

  async function load() {
    loading = true;
    loadError = null;
    try {
      items = await packingApi.list(tripId);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  async function addItem() {
    if (!newText.trim() || adding) return;
    const text = newText.trim();
    adding = true;
    newText = '';
    try {
      const { id } = await packingApi.create(tripId, text);
      items = [...items, {
        id,
        trip_id: tripId,
        text,
        checked: 0,
        sort_order: items.length,
        created_by: null,
        created_at: new Date().toISOString(),
      }];
    } catch (err) {
      newText = text;
      alert((err as Error).message);
    } finally {
      adding = false;
    }
  }

  async function toggleChecked(item: PackingItem) {
    const next = !item.checked;
    items = items.map((i) => (i.id === item.id ? { ...i, checked: next ? 1 : 0 } : i));
    try {
      await packingApi.update(tripId, item.id, { checked: next });
    } catch (err) {
      items = items.map((i) => (i.id === item.id ? { ...i, checked: item.checked } : i));
      alert((err as Error).message);
    }
  }

  function startEdit(item: PackingItem) {
    editingId = item.id;
    editText = item.text;
  }

  function cancelEdit() {
    editingId = null;
  }

  async function saveEdit() {
    if (!editingId || !editText.trim()) return;
    editSaving = true;
    try {
      await packingApi.update(tripId, editingId, { text: editText.trim() });
      items = items.map((i) => (i.id === editingId ? { ...i, text: editText.trim() } : i));
      editingId = null;
    } catch (err) {
      alert((err as Error).message);
    } finally {
      editSaving = false;
    }
  }

  async function deleteItem(item: PackingItem) {
    if (!confirm($t('packing.delete_confirm', { values: { name: item.text } }))) return;
    try {
      await packingApi.delete(tripId, item.id);
      items = items.filter((i) => i.id !== item.id);
    } catch (err) {
      alert((err as Error).message);
    }
  }

  async function clearChecked() {
    if (!confirm($t('packing.clear_checked') + '?')) return;
    try {
      await packingApi.clearChecked(tripId);
      items = items.filter((i) => !i.checked);
    } catch (err) {
      alert((err as Error).message);
    }
  }

  function handleAddKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') addItem();
  }

  function handleEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') saveEdit();
    if (e.key === 'Escape') cancelEdit();
  }
</script>

{#if loading}
  <p class="packing-empty">&hellip;</p>
{:else if loadError}
  <p class="packing-empty" style="color:var(--danger)">{loadError}</p>
{:else}
  {#if items.length > 0}
    {#if checkedCount > 0}
      <p class="packing-progress">
        {$t('packing.progress', { values: { done: checkedCount, total: items.length } })}
      </p>
    {/if}
    <ul class="packing-list">
      {#each items as item (item.id)}
        <li class="packing-item" class:is-checked={item.checked}>
          <button
            class="packing-checkbox"
            aria-label={item.checked ? $t('packing.uncheck') : $t('packing.check')}
            onclick={() => toggleChecked(item)}
          >
            {#if item.checked}
              <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="16" height="16" rx="3" fill="var(--primary)"/>
                <path d="M3.5 8L6.5 11L12.5 5" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            {:else}
              <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="0.5" y="0.5" width="15" height="15" rx="2.5" stroke="var(--border-strong, var(--border))"/>
              </svg>
            {/if}
          </button>

          {#if editingId === item.id}
            <input
              class="form-input packing-edit-input"
              type="text"
              bind:value={editText}
              onkeydown={handleEditKeydown}
              autofocus
            />
            <button
              class="btn btn-primary btn-sm"
              disabled={editSaving || !editText.trim()}
              onclick={saveEdit}
            >✓</button>
            <button class="btn btn-secondary btn-sm" onclick={cancelEdit}>✕</button>
          {:else}
            <span
              class="packing-text"
              role="button"
              tabindex="0"
              onclick={() => startEdit(item)}
              onkeydown={(e) => e.key === 'Enter' && startEdit(item)}
            >{item.text}</span>
            <button
              class="packing-delete btn-icon"
              aria-label={$t('packing.delete_item')}
              onclick={() => deleteItem(item)}
            >
              <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M3 4h10M6 4V3h4v1M5 4l.5 9h5L11 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {:else}
    <p class="packing-empty">{$t('packing.empty')}</p>
  {/if}

  <div class="packing-add-row">
    <input
      class="form-input packing-add-input"
      type="text"
      placeholder={$t('packing.add_placeholder')}
      bind:value={newText}
      onkeydown={handleAddKeydown}
    />
    <button
      class="btn btn-primary btn-sm"
      disabled={adding || !newText.trim()}
      onclick={addItem}
    >
      {$t('packing.add')}
    </button>
  </div>

  {#if hasChecked}
    <button class="btn btn-secondary btn-sm packing-clear-btn" onclick={clearChecked}>
      {$t('packing.clear_checked')}
    </button>
  {/if}
{/if}

<style>
  .packing-empty {
    font-size: 0.875rem;
    color: var(--text-muted);
    margin: 0 0 var(--space-sm);
  }

  .packing-progress {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin: 0 0 var(--space-xs);
  }

  .packing-list {
    list-style: none;
    padding: 0;
    margin: 0 0 var(--space-sm);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .packing-item {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
    min-height: 2.25rem;
  }

  .packing-checkbox {
    flex-shrink: 0;
    width: 1.25rem;
    height: 1.25rem;
    padding: 0;
    background: none;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: inherit;
  }

  .packing-checkbox svg {
    width: 1rem;
    height: 1rem;
  }

  .packing-text {
    flex: 1;
    font-size: 0.9rem;
    cursor: pointer;
    min-width: 0;
    word-break: break-word;
  }

  .is-checked .packing-text {
    text-decoration: line-through;
    color: var(--text-muted);
  }

  .packing-delete {
    flex-shrink: 0;
    opacity: 0;
    padding: 2px;
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    transition: opacity 0.15s, color 0.15s;
  }

  .packing-delete svg {
    width: 1rem;
    height: 1rem;
  }

  .packing-item:hover .packing-delete,
  .packing-item:focus-within .packing-delete {
    opacity: 1;
  }

  .packing-delete:hover {
    color: var(--danger);
  }

  .packing-edit-input {
    flex: 1;
    min-width: 0;
    font-size: 0.9rem;
    padding: 2px 6px;
    height: 1.75rem;
  }

  .packing-add-row {
    display: flex;
    gap: var(--space-xs);
    margin-top: var(--space-xs);
  }

  .packing-add-input {
    flex: 1;
    min-width: 0;
  }

  .packing-clear-btn {
    margin-top: var(--space-sm);
    font-size: 0.8rem;
  }
</style>
