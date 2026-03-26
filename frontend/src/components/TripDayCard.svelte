<script lang="ts">
  import type { Flight } from '../api/types';
  import { dayNotesApi } from '../api/client';
  import { untrack } from 'svelte';
  import { t, locale } from '../lib/i18n';

  interface ChecklistItem {
    text: string;
    checked: boolean;
  }

  export interface DayContent {
    note: string;
    items: ChecklistItem[];
  }

  interface Props {
    tripId: string;
    date: string;
    flights: Flight[];
    initialContent: DayContent;
    initiallyExpanded: boolean;
    forceExpanded?: boolean;
  }

  const { tripId, date, flights, initialContent, initiallyExpanded, forceExpanded = false }: Props = $props();

  // ---- Local state (isolated per card) ----
  // untrack: intentionally snapshot props at mount, changes after mount are ignored
  let note = $state(untrack(() => initialContent.note));
  let items = $state<ChecklistItem[]>(untrack(() => initialContent.items.map((i) => ({ ...i }))));
  let expanded = $state(untrack(() => initiallyExpanded));
  let saving = $state(false);
  let saved = $state(false);

  let pendingTimer: ReturnType<typeof setTimeout> | null = null;

  // ---- Derived preview for collapsed header ----
  const notePreviewText = $derived(note.split('\n').find((l) => l.trim()) ?? '');
  const firstItem = $derived(items[0] ?? null);

  // ---- Helpers ----

  function formatDayHeader(): string {
    const [y, m, d] = date.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    const loc = $locale ?? undefined;
    const weekday = dt.toLocaleDateString(loc, { weekday: 'short' });
    const month = dt.toLocaleDateString(loc, { month: 'long' });
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/\.$/, '');
    return `${cap(weekday)}, ${d} ${cap(month)}`;
  }

  function formatFlightTime(iso: string | null, tz: string | null): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleTimeString('en-GB', {
        hour: '2-digit', minute: '2-digit', hour12: false,
        timeZone: tz ?? undefined,
      });
    } catch {
      return iso.slice(11, 16);
    }
  }

  // ---- Mutations ----

  function toggleItem(idx: number) {
    items[idx] = { ...items[idx], checked: !items[idx].checked };
    scheduleSave();
  }

  function updateItemText(idx: number, text: string) {
    items[idx] = { ...items[idx], text };
    scheduleSave();
  }

  function addItem() {
    items = [...items, { text: '', checked: false }];
    scheduleSave();
  }

  function deleteItem(idx: number) {
    items = items.filter((_, i) => i !== idx);
    scheduleSave();
  }

  function onNoteInput(value: string) {
    note = value;
    scheduleSave();
  }

  // ---- Autosave ----

  function scheduleSave() {
    if (pendingTimer) clearTimeout(pendingTimer);
    pendingTimer = setTimeout(() => {
      pendingTimer = null;
      doSave();
    }, 600);
  }

  async function doSave() {
    saving = true;
    try {
      await dayNotesApi.upsert(tripId, date, JSON.stringify({ note, items }));
      saved = true;
      setTimeout(() => { saved = false; }, 1500);
    } catch {
      // silent — retry on next change
    } finally {
      saving = false;
    }
  }
</script>

<div class="day-card" class:expanded={expanded || forceExpanded}>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="day-card-header" onclick={() => (expanded = !expanded)}>
    <div class="day-card-header-left">
      <span class="day-label">{formatDayHeader()}</span>
      {#if !expanded && !forceExpanded}
        {#if flights.length > 0}
          <div class="day-flights-chips">
            {#each flights as f (f.id)}
              <span class="flight-chip">
                ✈ {f.departure_airport}→{f.arrival_airport} {formatFlightTime(f.departure_datetime, f.departure_timezone)}
              </span>
            {/each}
          </div>
        {/if}
        {#if notePreviewText}
          <span class="note-preview">{notePreviewText}</span>
        {/if}
        {#if firstItem}
          <span class="checklist-preview">
            <span class="check-preview-box" class:checked={firstItem.checked}>{firstItem.checked ? '✓' : ''}</span>
            <span class:done={firstItem.checked}>{firstItem.text || '…'}</span>
          </span>
        {/if}
        {#if !notePreviewText && !firstItem}
          <span class="note-hint">{$t('planner.add_notes_hint')}</span>
        {/if}
      {/if}
    </div>
    <div class="day-header-right">
      {#if saving}
        <span class="save-status saving">{$t('planner.saving')}</span>
      {:else if saved}
        <span class="save-status saved">✓</span>
      {/if}
      <span class="day-chevron">{expanded ? '▲' : '▼'}</span>
    </div>
  </div>

  {#if expanded || forceExpanded}
    <div class="day-card-body">
      <!-- Flights (read-only) -->
      {#if flights.length > 0}
        <div class="day-flights">
          {#each flights as f (f.id)}
            <div class="day-flight-row">
              <span class="day-flight-badge">✈</span>
              <span class="day-flight-info">
                <strong>{f.flight_number}</strong>
                {f.departure_airport} {formatFlightTime(f.departure_datetime, f.departure_timezone)}
                → {f.arrival_airport} {formatFlightTime(f.arrival_datetime, f.arrival_timezone)}
              </span>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Note -->
      <textarea
        class="note-textarea"
        placeholder={$t('planner.note_placeholder')}
        value={note}
        oninput={(e) => onNoteInput((e.currentTarget as HTMLTextAreaElement).value)}
        rows={3}
      ></textarea>

      <!-- Checklist -->
      <div class="checklist">
        {#each items as item, idx (idx)}
          <div class="checklist-item">
            <button
              class="check-btn"
              class:checked={item.checked}
              onclick={() => toggleItem(idx)}
              aria-label={item.checked ? $t('planner.uncheck') : $t('planner.check')}
            >{item.checked ? '✓' : ''}</button>
            <input
              type="text"
              class="check-input"
              class:done={item.checked}
              placeholder={$t('planner.checklist_item_placeholder')}
              value={item.text}
              oninput={(e) => updateItemText(idx, (e.currentTarget as HTMLInputElement).value)}
            />
            <button
              class="check-item-delete"
              onclick={() => deleteItem(idx)}
              aria-label={$t('planner.delete_item')}
            >✕</button>
          </div>
        {/each}
        <button class="add-item-btn" onclick={addItem}>
          + {$t('planner.add_item')}
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .day-card {
    border: 1px solid var(--border);
    border-radius: var(--radius-md, 8px);
    overflow: hidden;
    background: var(--surface);
  }

  .day-card-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    cursor: pointer;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
  }

  .day-card-header:active {
    background: var(--surface-hover, rgba(0,0,0,0.04));
  }

  .day-card-header-left {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .day-label {
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--text);
  }

  .day-flights-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 2px;
  }

  .flight-chip {
    font-size: 0.75rem;
    background: var(--primary-soft, rgba(59,130,246,0.1));
    color: var(--primary, #3b82f6);
    padding: 2px 7px;
    border-radius: 20px;
    white-space: nowrap;
  }

  .note-preview {
    font-size: 0.8rem;
    color: var(--text-secondary, var(--text-muted));
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .note-hint {
    font-size: 0.78rem;
    color: var(--text-muted);
    font-style: italic;
  }

  .day-header-right {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    flex-shrink: 0;
  }

  .save-status { font-size: 0.72rem; }
  .save-status.saving { color: var(--text-muted); }
  .save-status.saved { color: var(--success, #16a34a); font-weight: 600; }

  .day-chevron {
    font-size: 0.65rem;
    color: var(--text-muted);
  }

  .day-card-body {
    border-top: 1px solid var(--border);
    padding: var(--space-sm) var(--space-md) var(--space-md);
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .day-flights {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    background: var(--surface-2, var(--bg));
    border-radius: var(--radius-sm, 6px);
    padding: var(--space-sm);
  }

  .day-flight-row {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-size: 0.85rem;
  }

  .day-flight-badge { color: var(--primary, #3b82f6); flex-shrink: 0; }
  .day-flight-info { color: var(--text); }

  .note-textarea {
    width: 100%;
    box-sizing: border-box;
    font-family: inherit;
    font-size: 0.9rem;
    line-height: 1.55;
    padding: var(--space-sm);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    background: var(--input-bg, var(--surface));
    color: var(--text);
    resize: vertical;
    touch-action: manipulation;
  }

  .note-textarea:focus {
    outline: none;
    border-color: var(--primary, #3b82f6);
  }

  .checklist {
    display: flex;
    flex-direction: column;
    gap: 4px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    padding: var(--space-sm);
  }

  .checklist-item {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
  }

  .check-btn {
    width: 22px;
    height: 22px;
    min-width: 22px;
    border: 2px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    color: var(--success, #16a34a);
    padding: 0;
    touch-action: manipulation;
    transition: background 0.1s, border-color 0.1s;
  }

  .check-btn.checked {
    background: var(--success-bg, #dcfce7);
    border-color: var(--success, #16a34a);
  }

  .check-input {
    flex: 1;
    min-width: 0;
    border: none;
    background: transparent;
    font-size: 0.9rem;
    color: var(--text);
    padding: 2px 0;
    outline: none;
    touch-action: manipulation;
  }

  .check-input.done {
    text-decoration: line-through;
    color: var(--text-muted);
  }

  .check-item-delete {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.65rem;
    color: var(--text-muted);
    padding: 2px 4px;
    flex-shrink: 0;
    border-radius: 4px;
    touch-action: manipulation;
  }

  .check-item-delete:hover { color: var(--danger, #dc2626); }

  .add-item-btn {
    align-self: flex-start;
    margin-top: 2px;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.82rem;
    color: var(--primary, #3b82f6);
    padding: 2px 0;
    touch-action: manipulation;
  }

  /* Collapsed preview rows */
  .checklist-preview {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 0.8rem;
    color: var(--text-secondary, var(--text-muted));
  }

  .checklist-preview .done {
    text-decoration: line-through;
    color: var(--text-muted);
  }

  .check-preview-box {
    width: 14px;
    height: 14px;
    min-width: 14px;
    border: 1.5px solid var(--border);
    border-radius: 3px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    color: var(--success, #16a34a);
    flex-shrink: 0;
  }

  .check-preview-box.checked {
    background: var(--success-bg, #dcfce7);
    border-color: var(--success, #16a34a);
  }

  @media print {
    .save-status,
    .add-item-btn,
    .check-item-delete,
    .day-chevron { display: none !important; }

    .day-card { break-inside: avoid; border: 1px solid #ccc; }
    .check-btn { pointer-events: none; }
  }
</style>
