<script lang="ts">
  import { expensesApi } from '../api/client';
  import type { TripExpense } from '../api/types';
  import { t } from '../lib/i18n';

  interface Props {
    tripId: string;
    defaultCurrency?: string;
  }

  const { tripId, defaultCurrency = 'EUR' }: Props = $props();

  export const CURRENCIES = [
    'AED', 'ARS', 'AUD', 'BRL', 'CAD', 'CHF', 'CLP', 'CNY', 'COP',
    'CZK', 'DKK', 'EGP', 'EUR', 'GBP', 'HKD', 'HUF', 'IDR', 'ILS',
    'INR', 'ISK', 'JPY', 'KRW', 'MAD', 'MXN', 'MYR', 'NOK', 'NZD',
    'PEN', 'PHP', 'PLN', 'QAR', 'RON', 'SAR', 'SEK', 'SGD', 'THB',
    'TRY', 'TWD', 'UAH', 'USD', 'ZAR',
  ];

  let expenses = $state<TripExpense[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);

  // Add form
  let showAddForm = $state(false);
  let newDesc = $state('');
  let newAmount = $state<number | ''>('');
  let newCurrency = $state(defaultCurrency);
  let adding = $state(false);
  let addError = $state<string | null>(null);

  // Inline edit
  let editingId = $state<string | null>(null);
  let editDesc = $state('');
  let editAmount = $state<number | ''>('');
  let editCurrency = $state('');
  let editSaving = $state(false);

  async function load() {
    loading = true;
    loadError = null;
    try {
      expenses = await expensesApi.list(tripId);
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  load();

  const totals = $derived(
    expenses.reduce<Record<string, number>>((acc, e) => {
      acc[e.currency] = (acc[e.currency] ?? 0) + e.amount;
      return acc;
    }, {})
  );

  const sortedTotals = $derived(
    Object.entries(totals).sort(([a], [b]) => a.localeCompare(b))
  );

  function formatAmount(n: number): string {
    return n % 1 === 0
      ? n.toLocaleString()
      : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  async function addExpense() {
    const amount = Number(newAmount);
    if (!newDesc.trim() || !newAmount || isNaN(amount) || amount <= 0) return;
    adding = true;
    addError = null;
    try {
      await expensesApi.create(tripId, {
        description: newDesc.trim(),
        amount,
        currency: newCurrency,
      });
      newDesc = '';
      newAmount = '';
      newCurrency = defaultCurrency;
      showAddForm = false;
      await load();
    } catch (err) {
      addError = (err as Error).message;
    } finally {
      adding = false;
    }
  }

  function startEdit(expense: TripExpense) {
    editingId = expense.id;
    editDesc = expense.description;
    editAmount = expense.amount;
    editCurrency = expense.currency;
  }

  function cancelEdit() {
    editingId = null;
  }

  async function saveEdit() {
    if (!editingId) return;
    const amount = Number(editAmount);
    if (!editDesc.trim() || !editAmount || isNaN(amount) || amount <= 0) return;
    editSaving = true;
    try {
      await expensesApi.update(tripId, editingId, {
        description: editDesc.trim(),
        amount,
        currency: editCurrency,
      });
      editingId = null;
      await load();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      editSaving = false;
    }
  }

  async function deleteExpense(expense: TripExpense) {
    const label = `${expense.description} – ${formatAmount(expense.amount)} ${expense.currency}`;
    if (!confirm(`Delete expense "${label}"?`)) return;
    try {
      await expensesApi.delete(tripId, expense.id);
      expenses = expenses.filter((e) => e.id !== expense.id);
    } catch (err) {
      alert((err as Error).message);
    }
  }

  function openAddForm() {
    newCurrency = defaultCurrency;
    showAddForm = true;
    editingId = null;
  }

  function handleAddKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') addExpense();
    if (e.key === 'Escape') { showAddForm = false; addError = null; }
  }

  function handleEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') saveEdit();
    if (e.key === 'Escape') cancelEdit();
  }
</script>

{#if loading}
  <p class="expenses-empty">&hellip;</p>
{:else if loadError}
  <p class="expenses-empty" style="color:var(--danger)">{loadError}</p>
{:else}
  {#if expenses.length === 0 && !showAddForm}
    <p class="expenses-empty">{$t('expenses.empty')}</p>
  {:else}
    <div class="expenses-list">
      {#each expenses as expense (expense.id)}
        {#if editingId === expense.id}
          <!-- Inline edit row -->
          <div class="expense-edit-row">
            <input
              class="form-input expense-input-desc"
              type="text"
              bind:value={editDesc}
              onkeydown={handleEditKeydown}
              placeholder={$t('expenses.add_placeholder_desc')}
            />
            <input
              class="form-input expense-input-amount"
              type="number"
              min="0.01"
              step="any"
              bind:value={editAmount}
              onkeydown={handleEditKeydown}
              placeholder={$t('expenses.add_placeholder_amount')}
            />
            <select class="form-input expense-select-currency" bind:value={editCurrency}>
              {#each CURRENCIES as c}
                <option value={c}>{c}</option>
              {/each}
            </select>
            <div class="expense-edit-actions">
              <button
                class="btn btn-primary btn-sm"
                disabled={editSaving || !editDesc.trim() || !editAmount}
                onclick={saveEdit}
              >
                {editSaving ? $t('expenses.edit_saving') : $t('expenses.edit_save')}
              </button>
              <button class="btn btn-secondary btn-sm" onclick={cancelEdit}>
                {$t('expenses.edit_cancel')}
              </button>
            </div>
          </div>
        {:else}
          <!-- Display row -->
          <div class="expense-row">
            <span class="expense-desc">{expense.description}</span>
            <span class="expense-currency">{expense.currency}</span>
            <span class="expense-amount">{formatAmount(expense.amount)}</span>
            <div class="expense-actions">
              <button class="btn btn-secondary btn-sm" onclick={() => startEdit(expense)}>
                {$t('expenses.edit')}
              </button>
              <button class="btn btn-danger btn-sm" onclick={() => deleteExpense(expense)}>
                {$t('expenses.delete')}
              </button>
            </div>
          </div>
        {/if}
      {/each}
    </div>
  {/if}

  <!-- Totals -->
  {#if sortedTotals.length > 0}
    <div class="expenses-totals">
      <span class="expenses-total-label">{$t('expenses.total')}:</span>
      {#each sortedTotals as [currency, total]}
        <span class="expenses-total-pill">{currency} {formatAmount(total)}</span>
      {/each}
    </div>
  {/if}

  <!-- Add form -->
  {#if showAddForm}
    <div class="expense-add-form">
      <div class="expense-add-inputs">
        <input
          class="form-input expense-input-desc"
          type="text"
          bind:value={newDesc}
          onkeydown={handleAddKeydown}
          placeholder={$t('expenses.add_placeholder_desc')}
          autofocus
        />
        <input
          class="form-input expense-input-amount"
          type="number"
          min="0.01"
          step="any"
          bind:value={newAmount}
          onkeydown={handleAddKeydown}
          placeholder={$t('expenses.add_placeholder_amount')}
        />
        <select class="form-input expense-select-currency" bind:value={newCurrency}>
          {#each CURRENCIES as c}
            <option value={c}>{c}</option>
          {/each}
        </select>
      </div>
      <div class="expense-add-actions">
        <button
          class="btn btn-primary btn-sm"
          disabled={adding || !newDesc.trim() || !newAmount}
          onclick={addExpense}
        >
          {adding ? $t('expenses.saving') : $t('expenses.save')}
        </button>
        <button class="btn btn-secondary btn-sm" onclick={() => { showAddForm = false; addError = null; }}>
          {$t('expenses.cancel')}
        </button>
      </div>
      {#if addError}
        <p class="expense-error">{addError}</p>
      {/if}
    </div>
  {:else}
    <button class="btn btn-secondary btn-sm expenses-add-btn" onclick={openAddForm}>
      + {$t('expenses.add')}
    </button>
  {/if}
{/if}

<style>
  .expenses-empty {
    font-size: 0.875rem;
    color: var(--text-muted);
    margin: 0 0 var(--space-sm);
  }

  .expenses-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    margin-bottom: var(--space-sm);
  }

  .expense-row {
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-xs) 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.9rem;
  }

  .expense-desc {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .expense-currency {
    font-size: 0.8rem;
    color: var(--text-muted);
    min-width: 2.5rem;
    text-align: right;
  }

  .expense-amount {
    font-variant-numeric: tabular-nums;
    min-width: 5rem;
    text-align: right;
  }

  .expense-actions {
    display: flex;
    gap: var(--space-xs);
  }

  .expense-edit-row {
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-xs) 0;
    border-bottom: 1px solid var(--border);
  }

  .expense-edit-actions {
    display: flex;
    gap: var(--space-xs);
  }

  .expense-input-desc {
    min-width: 0;
  }

  .expense-input-amount {
    width: 7rem;
  }

  .expense-select-currency {
    width: 5.5rem;
  }

  .expenses-totals {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-sm) 0;
    border-top: 2px solid var(--border);
    font-size: 0.875rem;
  }

  .expenses-total-label {
    color: var(--text-muted);
    font-weight: 500;
  }

  .expenses-total-pill {
    background: var(--bg-subtle, var(--bg-card));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 4px);
    padding: 2px 8px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-size: 0.85rem;
  }

  .expense-add-form {
    margin-top: var(--space-sm);
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .expense-add-inputs {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: var(--space-xs);
  }

  .expense-add-actions {
    display: flex;
    gap: var(--space-xs);
  }

  .expense-error {
    color: var(--danger);
    font-size: 0.85rem;
    margin: var(--space-xs) 0 0;
  }

  .expenses-add-btn {
    margin-top: var(--space-xs);
  }

  @media (max-width: 540px) {
    .expense-row {
      grid-template-columns: 1fr auto;
      grid-template-rows: auto auto;
    }

    .expense-currency {
      grid-row: 2;
      text-align: left;
    }

    .expense-amount {
      grid-row: 2;
    }

    .expense-actions {
      grid-column: 2;
      grid-row: 1 / 3;
      align-self: center;
    }

    .expense-edit-row {
      grid-template-columns: 1fr;
    }

    .expense-input-amount,
    .expense-select-currency {
      width: 100%;
    }

    .expense-add-inputs {
      grid-template-columns: 1fr;
    }
  }
</style>
