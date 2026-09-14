<script lang="ts">
  import { budgetApi } from '../api/client';
  import type { TripBudget } from '../api/types';
  import { CURRENCIES } from '../lib/currencies';
  import { BUDGET_WARN_AT, budgetLevel, formatCurrencyTotals } from '../lib/utils';
  import { t } from '../lib/i18n';

  /**
   * A spending limit for this trip, and how close you are to it.
   *
   * Two decisions are load-bearing and both come from the backend:
   *
   * 1. **Spend is your own share.** An expense split four ways counts a quarter
   *    of it, whoever paid. What you paid out is a cash-flow question and the
   *    balances view answers that one; a budget is what the trip costs *you*.
   * 2. **Only the budget's currency counts.** Spend in any other currency is
   *    listed beside the bar and never converted — there are no exchange rates
   *    in this app, and a converted figure would be a guess presented as a fact.
   */
  interface Props {
    tripId: string;
    defaultCurrency?: string;
    /** Called after every read, so the trip header can print the same figure
     *  without fetching it a second time. */
    onchange?: (budget: TripBudget | null) => void;
  }

  const { tripId, defaultCurrency = 'EUR', onchange }: Props = $props();

  /* The thresholds live in `lib/utils` because the trip header shows the same
   * state in one line and the two must not drift apart.
   *
   * Green is otherwise reserved for "done" in this design language; here it is
   * the healthy end of one scale rather than a separate status, which is what
   * keeps it from competing with the badges that use it. */
  const WARN_AT = BUDGET_WARN_AT;

  let budget = $state<TripBudget | null>(null);
  let loadError = $state<string | null>(null);
  let editing = $state(false);
  let saving = $state(false);
  let formError = $state<string | null>(null);
  let amountInput = $state('');
  // Seeded when the form opens rather than at init, so a later
  // `defaultCurrency` is not ignored.
  let currencyInput = $state('');

  async function load() {
    try {
      budget = await budgetApi.get(tripId);
      loadError = null;
      onchange?.(budget);
    } catch (err) {
      loadError = (err as Error).message;
    }
  }

  load();

  /* Re-read after the expense list changes, called by the trip page through
   * `bind:this`.
   *
   * Deliberately a method and not a `revision` prop: bumping a counter from the
   * expense list's `onchange` re-renders the page, which hands the list a fresh
   * callback, which re-runs its reporting effect, which bumps the counter —
   * every trip-page test timed out on that loop before this became a call. */
  export function reload() {
    return load();
  }

  const hasBudget = $derived(budget?.amount != null && budget.currency != null);
  const ratio = $derived(
    hasBudget && budget!.amount! > 0 ? budget!.spent / budget!.amount! : 0,
  );
  const level = $derived(budgetLevel(budget?.spent ?? 0, budget?.amount) ?? 'under');

  /* How far through its own band the bar is, 0 (just entered) to 1 (about to
   * leave). The band picks the hue, this picks its strength — so the bar pales
   * in at the start of green, deepens across it, pales in again as amber, and
   * so on. A colour that only ever had three values told you which third you
   * were in; this also tells you where in the third, which is the part you
   * watch. The over-budget band tops out at +30%, past which there is nothing
   * left to say that a deeper red would say better. */
  const OVER_FULL_AT = 1.3;
  const intensity = $derived.by(() => {
    const span =
      level === 'under'
        ? ratio / WARN_AT
        : level === 'near'
          ? (ratio - WARN_AT) / (1 - WARN_AT)
          : (ratio - 1) / (OVER_FULL_AT - 1);
    return Math.max(0, Math.min(1, span));
  });
  /* Never below 35%: a bar mixed all the way into its own track is invisible,
   * and "I have spent almost nothing" still has to be readable as a bar. */
  const mix = $derived(Math.round(35 + intensity * 65));
  /* The bar stops at 100% while the *number* keeps going: a bar that overflows
   * its track says nothing the colour has not already said, and cannot show how
   * far over you are anyway. */
  const barWidth = $derived(Math.min(100, Math.round(ratio * 100)));
  const remaining = $derived(hasBudget ? budget!.amount! - budget!.spent : 0);
  const uncounted = $derived(formatCurrencyTotals(budget?.uncounted));

  function openEdit() {
    amountInput = budget?.amount != null ? String(budget.amount) : '';
    currencyInput = budget?.currency ?? defaultCurrency;
    formError = null;
    editing = true;
  }

  async function save() {
    const amount = Number(amountInput.replace(',', '.'));
    if (!Number.isFinite(amount) || amount <= 0) {
      formError = $t('budget.invalid_amount');
      return;
    }
    saving = true;
    formError = null;
    try {
      await budgetApi.set(tripId, amount, currencyInput);
      editing = false;
      await load();
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      saving = false;
    }
  }

  async function clear() {
    saving = true;
    try {
      await budgetApi.clear(tripId);
      editing = false;
      await load();
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      saving = false;
    }
  }

  function money(value: number, currency: string): string {
    return formatCurrencyTotals({ [currency]: value })[0] ?? `${currency} ${value}`;
  }
</script>

{#if loadError}
  <p class="budget-empty" style="color:var(--danger-text)">{loadError}</p>
{:else if editing}
  <div class="budget-form">
    <label class="form-field">
      <span class="form-label">{$t('budget.amount')}</span>
      <input
        class="form-input mono"
        type="text"
        inputmode="decimal"
        bind:value={amountInput}
        placeholder="800"
      />
    </label>
    <label class="form-field">
      <span class="form-label">{$t('budget.currency')}</span>
      <select class="form-input" bind:value={currencyInput}>
        {#each CURRENCIES as currency (currency)}
          <option value={currency}>{currency}</option>
        {/each}
      </select>
    </label>

    {#if formError}
      <p class="budget-error">{formError}</p>
    {/if}

    <div class="budget-actions">
      <button class="btn btn-primary btn-sm" disabled={saving} onclick={save}>
        {saving ? $t('budget.saving') : $t('budget.save')}
      </button>
      <button class="btn btn-secondary btn-sm" onclick={() => (editing = false)}>
        {$t('budget.cancel')}
      </button>
      {#if hasBudget}
        <button class="btn btn-secondary btn-sm" disabled={saving} onclick={clear}>
          {$t('budget.clear')}
        </button>
      {/if}
    </div>
  </div>
{:else if hasBudget}
  <div class="budget" data-level={level} style="--budget-mix:{mix}">
    <div class="budget-head">
      <span class="budget-figures">
        <strong class="budget-spent">{money(budget!.spent, budget!.currency!)}</strong>
        <span class="budget-of">{$t('budget.of')} {money(budget!.amount!, budget!.currency!)}</span>
      </span>
      <button class="btn btn-secondary btn-sm" onclick={openEdit}>{$t('budget.edit')}</button>
    </div>

    <div
      class="budget-track"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={budget!.amount!}
      aria-valuenow={budget!.spent}
    >
      <div class="budget-fill" style="width:{barWidth}%"></div>
    </div>

    <p class="budget-note">
      {#if remaining === 0}
        <!-- "EUR 0 over budget" is a strange way to say you spent exactly it. -->
        {$t('budget.reached')}
      {:else if level === 'over'}
        {$t('budget.over_by', { values: { amount: money(-remaining, budget!.currency!) } })}
      {:else}
        {$t('budget.left', { values: { amount: money(remaining, budget!.currency!) } })}
      {/if}
    </p>

    {#if uncounted.length > 0}
      <!-- Named, not converted. -->
      <p class="budget-uncounted">
        {$t('budget.uncounted')}
        {#each uncounted as label (label)}
          <span class="budget-uncounted-pill">{label}</span>
        {/each}
      </p>
    {/if}
  </div>
{:else}
  <div class="budget-empty-row">
    <p class="budget-empty">{$t('budget.none')}</p>
    <button class="btn btn-secondary btn-sm" onclick={openEdit}>{$t('budget.set')}</button>
  </div>
{/if}

<style>
  .budget-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-sm);
    flex-wrap: wrap;
  }

  .budget-figures {
    display: flex;
    align-items: baseline;
    gap: var(--space-xs);
    min-width: 0;
  }

  .budget-spent {
    font-family: var(--font-display);
    font-size: 1.25rem;
  }

  .budget-of {
    font-size: 0.85rem;
    color: var(--text-muted);
  }

  .budget-track {
    height: 8px;
    border-radius: 999px;
    background: var(--bg-subtle);
    overflow: hidden;
    margin: var(--space-sm) 0 var(--space-xs);
  }

  /* A traffic light that also dims and brightens: green while there is room,
     amber as it runs out, red once it is gone — each one paling in at the start
     of its band and deepening across it. The three hues are one scale rather
     than three statuses, which is why green can appear here without competing
     with the "done" badges.

     `background` is declared twice on purpose: the flat colour is what a
     browser without `color-mix` keeps, and it degrades to exactly the
     three-step bar this replaced rather than to nothing. */
  .budget-fill {
    height: 100%;
    border-radius: inherit;
    background: var(--budget-colour);
    background: color-mix(
      in oklab,
      var(--budget-colour) calc(var(--budget-mix, 100) * 1%),
      var(--bg-subtle)
    );
    transition:
      width 0.2s,
      background-color 0.2s;
  }

  .budget {
    --budget-colour: var(--success);
  }

  .budget[data-level='near'] {
    --budget-colour: var(--warning);
  }

  .budget[data-level='over'] {
    --budget-colour: var(--danger);
  }

  /* The text stays at full strength: a muted warning is a warning you skim. */
  .budget[data-level='near'] .budget-note {
    color: var(--warning-text);
  }

  .budget[data-level='over'] .budget-note,
  .budget[data-level='over'] .budget-spent {
    color: var(--danger-text);
  }

  .budget-note {
    margin: 0;
    font-size: 0.85rem;
    color: var(--text-muted);
  }

  .budget-uncounted {
    margin: var(--space-xs) 0 0;
    font-size: 0.78rem;
    color: var(--text-muted);
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px var(--space-xs);
  }

  .budget-uncounted-pill {
    font-family: var(--font-mono);
  }

  .budget-empty-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-sm);
    flex-wrap: wrap;
  }

  .budget-empty {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin: 0;
  }

  .budget-form {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }

  .budget-error {
    margin: 0;
    font-size: 0.85rem;
    color: var(--danger-text);
  }

  .budget-actions {
    display: flex;
    gap: var(--space-xs);
    flex-wrap: wrap;
  }
</style>
