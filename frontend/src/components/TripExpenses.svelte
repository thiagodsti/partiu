<script lang="ts">
  import { expensesApi, guestsApi } from '../api/client';
  import type { TripExpense, Participant, BalanceEntry, Guest } from '../api/types';
  import { CURRENCIES } from '../lib/currencies';
  import PeoplePicker from './PeoplePicker.svelte';
  import { currentUser } from '../lib/authStore';
  import { t } from '../lib/i18n';

  interface Props {
    tripId: string;
    defaultCurrency?: string;
    /** Called after load and after every mutation, so the trip header can show
     *  a total that is current rather than one fetched with the page. */
    onchange?: (totals: Record<string, number>) => void;
  }

  const { tripId, defaultCurrency = 'EUR', onchange }: Props = $props();

  function key(p: { type: string; id: number }): string {
    return `${p.type}:${p.id}`;
  }

  function parseKey(k: string): { type: 'user' | 'guest'; id: number } {
    const [ptype, pid] = k.split(':');
    return { type: ptype as 'user' | 'guest', id: Number(pid) };
  }

  function toggleKey(set: Set<string>, k: string): Set<string> {
    const next = new Set(set);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    return next;
  }

  /** Ensure an expense's own paid_by/participants stay selectable even if they've
   * since left the trip (e.g. a collaborator who was removed). */
  function withExpenseParticipants(base: Participant[], expense: TripExpense): Participant[] {
    const map = new Map(base.map((p) => [key(p), p]));
    map.set(key(expense.paid_by), expense.paid_by);
    for (const p of expense.participants) map.set(key(p), p);
    return Array.from(map.values());
  }

  /* `User.id` is a string on the wire while a participant's is a number, so
   * the two are compared through Number(). */
  const ownUserId = $derived($currentUser ? Number($currentUser.id) : null);
  const isMe = (p: Participant) => p.type === 'user' && p.id === ownUserId;
  /* You appear in the participant list like everyone else — the trip owner and
   * every accepted collaborator are in it — so your own row is marked rather
   * than offered a second time under a different name. The payer select used to
   * carry a separate "Me" option on top of it, which meant picking yourself was
   * two identically-meant choices. */
  const displayName = (p: Participant) =>
    isMe(p) ? $t('expenses.you', { values: { name: p.name } }) : p.name;

  let expenses = $state<TripExpense[]>([]);
  let participants = $state<Participant[]>([]);
  let myGuests = $state<Guest[]>([]);
  let balances = $state<Record<string, BalanceEntry[]>>({});
  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let showBalances = $state(false);
  let selectedForCombine = $state<Set<string>>(new Set());

  // Add form
  let showAddForm = $state(false);
  let newDesc = $state('');
  let newAmount = $state<number | ''>('');
  let newCurrency = $state(defaultCurrency);
  let newPaidByKey = $state('');
  let newParticipantKeys = $state<Set<string>>(new Set());
  let newGuestName = $state('');
  let adding = $state(false);
  let addingGuest = $state(false);
  let addError = $state<string | null>(null);

  // Inline edit
  let editingId = $state<string | null>(null);
  let editDesc = $state('');
  let editAmount = $state<number | ''>('');
  let editCurrency = $state('');
  let editPaidByKey = $state('');
  let editParticipantKeys = $state<Set<string>>(new Set());
  let editGuestName = $state('');
  let editSaving = $state(false);

  const editOptions = $derived.by(() => {
    if (!editingId) return participants;
    const expense = expenses.find((e) => e.id === editingId);
    return expense ? withExpenseParticipants(participants, expense) : participants;
  });

  const newGuestMatches = $derived.by(() => matchingGuests(newGuestName, newParticipantKeys));
  const editGuestMatches = $derived.by(() => matchingGuests(editGuestName, editParticipantKeys));

  /** Balance selections are scoped per currency — the same person shows up in
   * every currency group, but "combine" only makes sense within one currency
   * (there's no FX conversion), so checking them in EUR must not also check
   * them in BRL. */
  function balanceKey(currency: string, entry: { type: string; id: number }): string {
    return `${currency}:${key(entry)}`;
  }

  const combinedTotals = $derived.by(() => {
    const totals: Record<string, number> = {};
    for (const [currency, entries] of Object.entries(balances)) {
      let sum = 0;
      let any = false;
      for (const entry of entries) {
        if (selectedForCombine.has(balanceKey(currency, entry))) {
          sum += entry.net;
          any = true;
        }
      }
      if (any) totals[currency] = sum;
    }
    return totals;
  });

  async function fetchAll() {
    // Each call updates its own state slice independently — one endpoint
    // failing (or being transiently slow) must not stop the others from
    // reflecting a mutation that already succeeded on the server.
    const [exp, parts, bal, guests] = await Promise.all([
      expensesApi.list(tripId).catch((err) => { console.error(err); return expenses; }),
      expensesApi.participants(tripId).catch((err) => { console.error(err); return participants; }),
      expensesApi.balances(tripId).catch((err) => { console.error(err); return { balances }; }),
      guestsApi.list().catch((err) => { console.error(err); return myGuests; }),
    ]);
    expenses = exp;
    participants = parts;
    balances = bal.balances;
    myGuests = guests;
  }

  /** Guests you've already added on other trips that match what's being typed,
   * so you can reuse one instead of creating a duplicate — excludes guests
   * already selected for this expense. */
  function matchingGuests(typed: string, selectedKeys: Set<string>): Guest[] {
    const query = typed.trim().toLowerCase();
    if (!query) return [];
    return myGuests
      .filter((g) => g.name.toLowerCase().includes(query) && !selectedKeys.has(`guest:${g.id}`))
      .slice(0, 5);
  }

  async function load() {
    loading = true;
    loadError = null;
    try {
      await fetchAll();
    } catch (err) {
      loadError = (err as Error).message;
    } finally {
      loading = false;
    }
  }

  /** Re-fetch after a mutation without blanking the already-rendered list —
   * a transient failure here shouldn't hide expenses that just saved fine. */
  async function refresh() {
    try {
      await fetchAll();
    } catch (err) {
      alert((err as Error).message);
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

  /* Report upward whenever the totals move — the list is the only thing that
   * knows an expense was added, edited or deleted.
   *
   * Gated on `loading`, because the effect runs once on mount with an empty
   * list and an empty object is not nullish: the trip header, which seeds
   * itself from the trip payload and falls back to it, would take `{}` as the
   * real answer and show no total at all. A failed load is silent for the same
   * reason: the seeded total is better than none. */
  $effect(() => {
    if (!loading && !loadError) onchange?.(totals);
  });

  function formatAmount(n: number): string {
    return n % 1 === 0
      ? n.toLocaleString()
      : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatSigned(n: number): string {
    return `${n >= 0 ? '+' : ''}${formatAmount(n)}`;
  }

  async function addExpense() {
    const amount = Number(newAmount);
    if (!newDesc.trim() || !newAmount || isNaN(amount) || amount <= 0) return;
    if (newParticipantKeys.size === 0) return;
    adding = true;
    addError = null;
    const desc = newDesc.trim();
    const currency = newCurrency;
    const paidBy = newPaidByKey ? parseKey(newPaidByKey) : undefined;
    const participantsPayload = Array.from(newParticipantKeys).map(parseKey);
    try {
      await expensesApi.create(tripId, {
        description: desc,
        amount,
        currency,
        paid_by: paidBy,
        participants: participantsPayload,
      });
      newDesc = '';
      newAmount = '';
      newCurrency = defaultCurrency;
      showAddForm = false;
      await refresh();
    } catch (err) {
      addError = (err as Error).message;
    } finally {
      adding = false;
    }
  }

  async function handleAddGuest(target: 'add' | 'edit') {
    const name = (target === 'add' ? newGuestName : editGuestName).trim();
    if (!name) return;
    addingGuest = true;
    try {
      const { id } = await guestsApi.create(name);
      myGuests = [...myGuests, { id, name, created_at: new Date().toISOString() }];
      selectGuest(target, { type: 'guest', id, name });
    } catch (err) {
      alert((err as Error).message);
    } finally {
      addingGuest = false;
    }
  }

  /** Reuse a guest already in your address book (e.g. from another trip)
   * instead of creating a duplicate. */
  function selectGuest(target: 'add' | 'edit', guest: Participant) {
    if (!participants.some((p) => p.type === 'guest' && p.id === guest.id)) {
      participants = [...participants, guest];
    }
    if (target === 'add') {
      newGuestName = '';
      newParticipantKeys = new Set([...newParticipantKeys, key(guest)]);
    } else {
      editGuestName = '';
      editParticipantKeys = new Set([...editParticipantKeys, key(guest)]);
    }
  }

  function startEdit(expense: TripExpense) {
    editingId = expense.id;
    editDesc = expense.description;
    editAmount = expense.amount;
    editCurrency = expense.currency;
    editPaidByKey = key(expense.paid_by);
    editParticipantKeys = new Set(expense.participants.map(key));
    editGuestName = '';
    showAddForm = false;
  }

  function cancelEdit() {
    editingId = null;
  }

  async function saveEdit() {
    if (!editingId) return;
    const amount = Number(editAmount);
    if (!editDesc.trim() || !editAmount || isNaN(amount) || amount <= 0) return;
    if (editParticipantKeys.size === 0) return;
    editSaving = true;
    const id = editingId;
    const desc = editDesc.trim();
    const currency = editCurrency;
    const paidBy = parseKey(editPaidByKey);
    const participantsPayload = Array.from(editParticipantKeys).map(parseKey);
    try {
      await expensesApi.update(tripId, id, {
        description: desc,
        amount,
        currency,
        paid_by: paidBy,
        participants: participantsPayload,
      });
      editingId = null;
      await refresh();
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
      await refresh();
    } catch (err) {
      alert((err as Error).message);
    }
  }

  function openAddForm() {
    newCurrency = defaultCurrency;
    // Yourself, by key, rather than an empty "default to the creator" value:
    // the two rendered as two separate options for the same person.
    newPaidByKey = ownParticipantKey();
    newParticipantKeys = new Set(participants.map(key));
    newGuestName = '';
    showAddForm = true;
    editingId = null;
  }

  /** Your own row in the trip's participant list, or '' if the list has not
   *  loaded — in which case the payer is omitted and the backend falls back to
   *  the creator, which is you. */
  function ownParticipantKey(): string {
    const me = participants.find(isMe);
    return me ? key(me) : '';
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

{#snippet checkboxIcon(checked: boolean)}
  {#if checked}
    <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="16" height="16" rx="3" fill="var(--accent)"/>
      <!-- `--accent-on`, never a hardcoded white: on the paler presets the
           fill is near-white and a white tick disappears into it. -->
      <path d="M3.5 8L6.5 11L12.5 5" stroke="var(--accent-on)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  {:else}
    <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="0.5" y="0.5" width="15" height="15" rx="2.5" stroke="var(--border-strong, var(--border))"/>
    </svg>
  {/if}
{/snippet}

{#snippet guestSuggestions(matches: Guest[], target: 'add' | 'edit')}
  {#if matches.length > 0}
    <div class="guest-suggestions">
      <span class="guest-suggestions-label">{$t('expenses.pick_existing_guest')}</span>
      {#each matches as guest (guest.id)}
        <button
          type="button"
          class="guest-suggestion-chip"
          onclick={() => selectGuest(target, { type: 'guest', id: guest.id, name: guest.name })}
        >
          {guest.name}
        </button>
      {/each}
    </div>
  {/if}
{/snippet}

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
            <div class="expense-split-row">
              <label class="expense-split-label" for="edit-paid-by-{expense.id}">{$t('expenses.paid_by')}</label>
              <select id="edit-paid-by-{expense.id}" class="form-input" bind:value={editPaidByKey}>
                {#each editOptions as p (key(p))}
                  <option value={key(p)}>{displayName(p)}</option>
                {/each}
              </select>
            </div>
            <div class="expense-split-row">
              <PeoplePicker
                people={editOptions}
                selected={editParticipantKeys}
                onToggle={(p) => (editParticipantKeys = toggleKey(editParticipantKeys, key(p)))}
                label={$t('expenses.split_between')}
                display={displayName}
              />
              <div class="expense-add-guest-inline">
                <input
                  class="form-input"
                  type="text"
                  bind:value={editGuestName}
                  placeholder={$t('expenses.add_guest_placeholder')}
                  onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddGuest('edit'); } }}
                />
                <button
                  class="btn btn-secondary btn-sm"
                  type="button"
                  disabled={addingGuest || !editGuestName.trim()}
                  onclick={() => handleAddGuest('edit')}
                >
                  + {$t('expenses.add_guest')}
                </button>
              </div>
              {@render guestSuggestions(editGuestMatches, 'edit')}
            </div>
          </div>
        {:else}
          <!-- Display row -->
          <div class="expense-row">
            <div class="expense-main">
              <span class="expense-desc">{expense.description}</span>
              <span class="expense-meta">
                {$t('expenses.paid_by_label', { values: { name: expense.paid_by.name } })}
                · {$t('expenses.split_count', { values: { n: expense.participants.length } })}
                {#if expense.created_by_username}
                  · {$t('expenses.added_by', { values: { name: expense.created_by_username } })}
                {/if}
              </span>
            </div>
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

  <!-- Balances -->
  {#if Object.keys(balances).length > 0}
    <div class="expenses-balances">
      <button class="btn btn-secondary btn-sm" type="button" onclick={() => showBalances = !showBalances}>
        {showBalances ? $t('expenses.balances_hide') : $t('expenses.balances_show')}
      </button>
      {#if showBalances}
        {#each Object.entries(balances) as [currency, entries] (currency)}
          <div class="balances-currency-group">
            <h4 class="balances-currency-title">{currency}</h4>
            <div class="balances-list">
              {#each entries as entry (key(entry))}
                <button
                  type="button"
                  class="balance-row"
                  aria-pressed={selectedForCombine.has(balanceKey(currency, entry))}
                  onclick={() => selectedForCombine = toggleKey(selectedForCombine, balanceKey(currency, entry))}
                >
                  <span class="mini-checkbox">{@render checkboxIcon(selectedForCombine.has(balanceKey(currency, entry)))}</span>
                  <span class="balance-name">{entry.name}</span>
                  <span class="balance-net" class:positive={entry.net > 0.005} class:negative={entry.net < -0.005}>
                    {formatSigned(entry.net)}
                  </span>
                </button>
              {/each}
            </div>
            {#if combinedTotals[currency] !== undefined}
              <div class="balance-combined">
                {$t('expenses.combined_total')}: {formatSigned(combinedTotals[currency])} {currency}
              </div>
            {/if}
          </div>
        {/each}
      {/if}
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
      <div class="expense-split-row">
        <label class="expense-split-label" for="new-paid-by">{$t('expenses.paid_by')}</label>
        <select id="new-paid-by" class="form-input" bind:value={newPaidByKey}>
          {#if participants.length === 0}
            <!-- Only when the list is unavailable: with it loaded you are in it,
                 and a separate "Me" would be the same person offered twice. -->
            <option value="">{$t('expenses.paid_by_me')}</option>
          {/if}
          {#each participants as p (key(p))}
            <option value={key(p)}>{displayName(p)}</option>
          {/each}
        </select>
      </div>
      <div class="expense-split-row">
        <PeoplePicker
          people={participants}
          selected={newParticipantKeys}
          onToggle={(p) => (newParticipantKeys = toggleKey(newParticipantKeys, key(p)))}
          label={$t('expenses.split_between')}
          display={displayName}
        />
        <div class="expense-add-guest-inline">
          <input
            class="form-input"
            type="text"
            bind:value={newGuestName}
            placeholder={$t('expenses.add_guest_placeholder')}
            onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddGuest('add'); } }}
          />
          <button
            class="btn btn-secondary btn-sm"
            type="button"
            disabled={addingGuest || !newGuestName.trim()}
            onclick={() => handleAddGuest('add')}
          >
            + {$t('expenses.add_guest')}
          </button>
        </div>
        {@render guestSuggestions(newGuestMatches, 'add')}
      </div>
      <div class="expense-add-actions">
        <button
          class="btn btn-primary btn-sm"
          disabled={adding || !newDesc.trim() || !newAmount || newParticipantKeys.size === 0}
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
    /* The rows have to answer to the width they actually get, not the window's.
       In the trip page's sidebar this list is ~380px wide on a 1400px screen,
       where a viewport media query still thinks it is on a desktop. */
    container-type: inline-size;
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

  .expense-main {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .expense-desc {
    /* Wraps rather than truncating. The amount and the buttons are fixed-width,
       so in a narrow column the description was the only thing that gave, and
       it is the only part of the row that says what the money was for —
       "Lunch in Rei..." and "Airport c..." are two lines of nothing. */
    overflow-wrap: anywhere;
  }

  .expense-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
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

  .expense-split-row {
    grid-column: 1 / -1;
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    padding-top: var(--space-xs);
  }

  .expense-split-label {
    font-size: 0.8rem;
    color: var(--text-muted);
    font-weight: 500;
  }

  .mini-checkbox {
    flex-shrink: 0;
    width: 1.25rem;
    height: 1.25rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .mini-checkbox svg {
    width: 1rem;
    height: 1rem;
  }

  .expense-add-guest-inline {
    display: flex;
    gap: var(--space-xs);
    align-items: center;
  }

  .expense-add-guest-inline .form-input {
    max-width: 12rem;
  }

  .guest-suggestions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-top: 4px;
  }

  .guest-suggestions-label {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .guest-suggestion-chip {
    background: var(--bg-subtle, var(--bg-card));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 4px);
    padding: 2px 8px;
    font-size: 0.8rem;
    cursor: pointer;
    color: inherit;
  }

  .guest-suggestion-chip:hover {
    border-color: var(--accent);
    color: var(--accent);
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

  .expenses-balances {
    padding: var(--space-sm) 0;
    border-top: 1px solid var(--border);
  }

  .balances-currency-group {
    margin-top: var(--space-sm);
  }

  .balances-currency-title {
    margin: 0 0 var(--space-xs);
    font-size: 0.85rem;
    color: var(--text-muted);
  }

  .balances-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .balance-row {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    font-size: 0.875rem;
    background: none;
    border: none;
    padding: 0;
    width: 100%;
    color: inherit;
    font-family: inherit;
    text-align: left;
    cursor: pointer;
  }

  .balance-name {
    flex: 1;
  }

  .balance-net {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }

  .balance-net.positive {
    color: var(--success, #2a9d5c);
  }

  .balance-net.negative {
    color: var(--danger);
  }

  .balance-combined {
    margin-top: var(--space-xs);
    font-size: 0.85rem;
    font-weight: 600;
  }

  .expense-add-form {
    margin-top: var(--space-sm);
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
  }

  .expense-add-form {
    container-type: inline-size;
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

  /* Narrow *container*, not narrow window: this is the phone layout, and the
     sidebar column needs it too. Description keeps the first row to itself;
     currency and amount drop below it; the buttons span both rows. */
  @container (max-width: 480px) {
    .expense-row {
      grid-template-columns: auto 1fr auto;
      grid-template-areas:
        'main main main'
        'currency amount actions';
      align-items: center;
      row-gap: var(--space-xs);
    }

    /* The description gets the full width of the row rather than sharing it
       with the buttons — otherwise a four-word expense wraps to three lines
       against a column of empty space. */
    .expense-main {
      grid-area: main;
    }

    .expense-currency {
      grid-area: currency;
      text-align: left;
      min-width: 0;
    }

    .expense-amount {
      grid-area: amount;
      text-align: left;
      min-width: 0;
    }

    .expense-actions {
      grid-area: actions;
    }

    .expense-edit-row {
      grid-template-columns: 1fr;
    }

    .expense-edit-row .expense-input-amount,
    .expense-edit-row .expense-select-currency {
      width: 100%;
    }

    .expense-add-inputs {
      grid-template-columns: 1fr;
    }

    .expense-add-inputs .expense-input-amount,
    .expense-add-inputs .expense-select-currency {
      width: 100%;
    }
  }
</style>
