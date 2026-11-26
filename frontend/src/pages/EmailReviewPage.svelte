<script lang="ts">
  /* Booking emails the sync could not read (backend/email_review). Each shows
   * what was found in it — chips to click into the form — and the lines those
   * values came from. "Create trip" opens a leg form to fill by hand; "Fill
   * with AI" (when Ollama is set up) asks the LLM for a draft of the same
   * form. Nothing is saved until "Import". */
  import { emailReviewApi, ApiError, type ReviewCandidate, type ReviewLeg } from '../api/client';
  import TopNav from '../components/TopNav.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import LoadingScreen from '../components/LoadingScreen.svelte';
  import { t, locale } from '../lib/i18n';
  import { toasts } from '../lib/toastStore';
  import { applyChip, highlight, type ChipKind, type LegField } from '../lib/reviewChips';

  let loading = $state(true);
  let loadError = $state('');
  let items = $state<ReviewCandidate[]>([]);
  let aiAvailable = $state(false);

  // Per-candidate form state.
  let forms = $state<Record<string, ReviewLeg[]>>({});
  let busy = $state<Record<string, 'ai' | 'import' | ''>>({});
  let notes = $state<Record<string, { text: string; tone: 'info' | 'error' }>>({});
  let focused = $state<{ id: string; leg: number; field: LegField } | null>(null);
  // The AI's guesses the email does not support, per candidate and leg:
  // shown under the field, never filled in.
  let doubts = $state<Record<string, Record<string, string>[]>>({});

  async function load() {
    loading = true;
    try {
      const r = await emailReviewApi.list();
      items = r.items;
      aiAvailable = r.ai_available;
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  load();

  const emptyLeg = (ref: string | null): ReviewLeg => ({
    flight_number: '',
    departure_airport: '',
    arrival_airport: '',
    departure_datetime: '',
    arrival_datetime: '',
    booking_reference: ref ?? '',
  });

  function openForm(c: ReviewCandidate) {
    doubts[c.id] = [];
    forms[c.id] = [emptyLeg(c.hints.booking_reference)];
    notes[c.id] = { text: '', tone: 'info' };
  }

  function removeLeg(id: string, index: number) {
    forms[id].splice(index, 1);
    doubts[id]?.splice(index, 1);
    // The focused field may have pointed at the removed row or past the end.
    if (focused?.id === id) focused = null;
  }

  // Bumped by Cancel, so an AI answer that arrives afterwards is dropped
  // instead of reopening the form the user just closed.
  let generation = $state<Record<string, number>>({});

  function cancelForm(id: string) {
    generation[id] = (generation[id] ?? 0) + 1;
    delete forms[id];
    if (focused?.id === id) focused = null;
    notes[id] = { text: '', tone: 'info' };
    busy[id] = '';
  }

  async function fillWithAi(c: ReviewCandidate) {
    if (busy[c.id]) return;
    const mine = (generation[c.id] = (generation[c.id] ?? 0) + 1);
    busy[c.id] = 'ai';
    notes[c.id] = { text: $t('review.ai_running'), tone: 'info' };
    try {
      const { legs } = await emailReviewApi.draft(c.id);
      if (generation[c.id] !== mine) return;
      if (legs.length) {
        doubts[c.id] = legs.map((l) => l.doubts ?? {});
        forms[c.id] = legs.map(({ doubts: _d, ...l }) => ({ ...l, booking_reference: l.booking_reference || c.hints.booking_reference || '' }));
        notes[c.id] = { text: $t('review.ai_check'), tone: 'info' };
      } else {
        forms[c.id] = forms[c.id] ?? [emptyLeg(c.hints.booking_reference)];
        notes[c.id] = { text: $t('review.ai_nothing'), tone: 'info' };
      }
    } catch (e) {
      if (generation[c.id] !== mine) return;
      forms[c.id] = forms[c.id] ?? [emptyLeg(c.hints.booking_reference)];
      const text =
        e instanceof ApiError && e.code === 'ai_unreachable'
          ? $t('review.ai_unreachable')
          : e instanceof Error
            ? e.message
            : String(e);
      notes[c.id] = { text, tone: 'error' };
    } finally {
      if (generation[c.id] === mine) busy[c.id] = '';
    }
  }

  function chip(c: ReviewCandidate, kind: ChipKind, value: string) {
    if (!forms[c.id]) openForm(c);
    const target = focused && focused.id === c.id ? focused : null;
    const legs = forms[c.id];
    if (kind === 'ref') {
      legs.forEach((l) => (l.booking_reference = value));
      return;
    }
    if (!target) return;
    const leg = legs[target.leg];
    if (!leg) return;
    const emailYear = c.email_date ? new Date(c.email_date).getFullYear() : undefined;
    const next = applyChip(target.field, leg[target.field], kind, value, emailYear);
    if (next !== null) leg[target.field] = next;
  }

  async function doImport(c: ReviewCandidate) {
    if (busy[c.id]) return;
    busy[c.id] = 'import';
    try {
      const legs = forms[c.id].map((l) => ({
        ...l,
        flight_number: l.flight_number.trim(),
        departure_airport: l.departure_airport.trim().toUpperCase(),
        arrival_airport: l.arrival_airport.trim().toUpperCase(),
      }));
      const r = await emailReviewApi.importLegs(c.id, legs);
      items = items.filter((i) => i.id !== c.id);
      toasts.show($t('review.imported', { values: { count: r.flight_ids.length } }), 'success');
      if (r.trip_ids[0]) window.location.hash = `/trips/${r.trip_ids[0]}`;
    } catch (e) {
      const msg = e instanceof ApiError || e instanceof Error ? e.message : String(e);
      notes[c.id] = { text: msg, tone: 'error' };
    } finally {
      busy[c.id] = '';
    }
  }

  async function dismiss(c: ReviewCandidate) {
    await emailReviewApi.dismiss(c.id);
    items = items.filter((i) => i.id !== c.id);
  }

  function domainOf(sender: string | null): string {
    return (sender ?? '').match(/@([\w.-]+)/)?.[1] ?? (sender ?? '');
  }

  async function ignoreSender(c: ReviewCandidate) {
    const domain = domainOf(c.sender);
    if (!confirm($t('review.ignore_confirm', { values: { domain } }))) return;
    await emailReviewApi.ignoreSender(c.id);
    items = items.filter((i) => domainOf(i.sender).toLowerCase() !== domain.toLowerCase());
  }

  function formatDate(iso: string | null): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString($locale ?? undefined, {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      });
    } catch {
      return iso.slice(0, 10);
    }
  }

  const needles = (c: ReviewCandidate) => [
    ...c.hints.flight_numbers,
    ...c.hints.airports,
    ...(c.hints.booking_reference ? [c.hints.booking_reference] : []),
  ];

  const isFocused = (id: string, leg: number, field: LegField) =>
    focused?.id === id && focused.leg === leg && focused.field === field;
</script>

<TopNav title={$t('review.title')} backHref="#/trips" />

<div class="main-content review-page">
  {#if loading}
    <LoadingScreen message="" />
  {:else if loadError}
    <EmptyState icon="⚠️" title={$t('review.load_error')} description={loadError} />
  {:else if items.length === 0}
    <EmptyState icon="✉️" title={$t('review.empty_title')} description={$t('review.empty_desc')} />
  {:else}
    <p class="review-intro">{$t('review.intro')}</p>
    {#if !aiAvailable}
      <p class="form-hint review-ai-hint" data-testid="ai-unavailable">✨ {$t('review.ai_unavailable')}</p>
    {/if}

    {#each items as c (c.id)}
      <article class="trip-section review-card" data-testid="review-card">
        <header class="review-head">
          <h2 class="review-subject">{c.subject}</h2>
          <div class="review-meta">
            <span class="review-sender">{c.sender}</span>
            {#if c.email_date}<span aria-hidden="true">·</span><span>{formatDate(c.email_date)}</span>{/if}
          </div>
        </header>

        <section class="review-found">
          <div class="review-label">{$t('review.found')}</div>
          <div class="chip-groups">
            {#each [
              ['review.flight_numbers', 'flight', c.hints.flight_numbers],
              ['review.airports', 'airport', c.hints.airports],
              ['review.dates', 'date', c.hints.dates],
              ['review.times', 'time', c.hints.times],
            ] as [label, kind, values] (label)}
              {#if (values as string[]).length}
                <div class="chip-group">
                  <span class="chip-group-label">{$t(label as string)}</span>
                  {#each values as string[] as v (v)}
                    <button type="button" class="chip" class:mono={kind !== 'date'} onclick={() => chip(c, kind as ChipKind, v)}>{v}</button>
                  {/each}
                </div>
              {/if}
            {/each}
            {#if c.hints.booking_reference}
              <div class="chip-group">
                <span class="chip-group-label">{$t('review.booking_ref')}</span>
                <button type="button" class="chip mono" onclick={() => chip(c, 'ref', c.hints.booking_reference!)}>{c.hints.booking_reference}</button>
              </div>
            {/if}
          </div>
          {#if forms[c.id]}<p class="form-hint">{$t('review.found_hint')}</p>{/if}
        </section>

        {#if c.hints.excerpt.length}
          <details class="review-excerpt" open={!forms[c.id]}>
            <summary class="review-label">{$t('review.excerpt')}</summary>
            <div class="excerpt-lines">
              {#each c.hints.excerpt as line, i (i)}
                <div class="excerpt-line">
                  {#each highlight(line, needles(c)) as part, j (j)}{#if part.hit}<mark>{part.text}</mark>{:else}{part.text}{/if}{/each}
                </div>
              {/each}
            </div>
          </details>
        {/if}

        {#if notes[c.id]?.text}
          <p class={notes[c.id].tone === 'error' ? 'form-error' : 'form-hint review-note'}>
            {#if busy[c.id] === 'ai'}<span class="spinner"></span>{/if}
            {notes[c.id].text}
          </p>
        {/if}

        {#if forms[c.id]}
          <div class="review-form">
            {#each forms[c.id] as leg, li (li)}
              <fieldset class="review-leg">
                <legend>{$t('review.flight', { values: { n: li + 1 } })}</legend>
                <div class="form-row">
                  <div class="form-field">
                    <label class="form-label" for="fn-{c.id}-{li}">{$t('review.flight_number')}</label>
                    <input id="fn-{c.id}-{li}" class="form-input mono" class:target={isFocused(c.id, li, 'flight_number')} bind:value={leg.flight_number} onfocus={() => (focused = { id: c.id, leg: li, field: 'flight_number' })} />
                    {#if doubts[c.id]?.[li]?.flight_number}<p class="doubt">{$t('review.ai_guess', { values: { value: doubts[c.id][li].flight_number } })}</p>{/if}
                  </div>
                  <div class="form-field airport-field">
                    <label class="form-label" for="from-{c.id}-{li}">{$t('review.from')}</label>
                    <input id="from-{c.id}-{li}" class="form-input mono" class:target={isFocused(c.id, li, 'departure_airport')} bind:value={leg.departure_airport} maxlength="3" onfocus={() => (focused = { id: c.id, leg: li, field: 'departure_airport' })} />
                    {#if doubts[c.id]?.[li]?.departure_airport}<p class="doubt">{$t('review.ai_guess', { values: { value: doubts[c.id][li].departure_airport } })}</p>{/if}
                  </div>
                  <div class="form-field airport-field">
                    <label class="form-label" for="to-{c.id}-{li}">{$t('review.to')}</label>
                    <input id="to-{c.id}-{li}" class="form-input mono" class:target={isFocused(c.id, li, 'arrival_airport')} bind:value={leg.arrival_airport} maxlength="3" onfocus={() => (focused = { id: c.id, leg: li, field: 'arrival_airport' })} />
                    {#if doubts[c.id]?.[li]?.arrival_airport}<p class="doubt">{$t('review.ai_guess', { values: { value: doubts[c.id][li].arrival_airport } })}</p>{/if}
                  </div>
                </div>
                <div class="form-row">
                  <div class="form-field">
                    <label class="form-label" for="dep-{c.id}-{li}">{$t('review.departure')}</label>
                    <input id="dep-{c.id}-{li}" type="datetime-local" class="form-input" class:target={isFocused(c.id, li, 'departure_datetime')} bind:value={leg.departure_datetime} onfocus={() => (focused = { id: c.id, leg: li, field: 'departure_datetime' })} />
                    {#if doubts[c.id]?.[li]?.departure_datetime}<p class="doubt">{$t('review.ai_guess', { values: { value: doubts[c.id][li].departure_datetime } })}</p>{/if}
                  </div>
                  <div class="form-field">
                    <label class="form-label" for="arr-{c.id}-{li}">{$t('review.arrival')}</label>
                    <input id="arr-{c.id}-{li}" type="datetime-local" class="form-input" class:target={isFocused(c.id, li, 'arrival_datetime')} bind:value={leg.arrival_datetime} onfocus={() => (focused = { id: c.id, leg: li, field: 'arrival_datetime' })} />
                    {#if doubts[c.id]?.[li]?.arrival_datetime}<p class="doubt">{$t('review.ai_guess', { values: { value: doubts[c.id][li].arrival_datetime } })}</p>{/if}
                  </div>
                </div>
                {#if forms[c.id].length > 1}
                  <button type="button" class="btn btn-secondary btn-sm" onclick={() => removeLeg(c.id, li)}>{$t('review.remove_flight')}</button>
                {/if}
              </fieldset>
            {/each}
            <div class="form-row">
              <div class="form-field">
                <label class="form-label" for="ref-{c.id}">{$t('review.booking_ref')}</label>
                <input id="ref-{c.id}" class="form-input mono" value={forms[c.id][0]?.booking_reference ?? ''} oninput={(e) => forms[c.id].forEach((l) => (l.booking_reference = (e.currentTarget as HTMLInputElement).value))} />
              </div>
            </div>
            <div class="review-form-actions">
              <button type="button" class="btn btn-secondary btn-sm" onclick={() => forms[c.id].push(emptyLeg(forms[c.id][0]?.booking_reference ?? null))}>{$t('review.add_flight')}</button>
              <span class="spacer"></span>
              <button type="button" class="btn btn-secondary" onclick={() => cancelForm(c.id)}>{$t('review.cancel')}</button>
              <button type="button" class="btn btn-primary" disabled={!!busy[c.id]} onclick={() => doImport(c)}>
                {busy[c.id] === 'import' ? $t('review.importing') : $t('review.import')}
              </button>
            </div>
          </div>
        {/if}

        <footer class="review-actions">
          {#if !forms[c.id]}
            <button type="button" class="btn btn-primary btn-sm" onclick={() => openForm(c)}>{$t('review.create')}</button>
          {/if}
          <!-- Shown even without an AI, disabled: it tells the reader the
               better path exists. The reason is spelled out under the intro,
               since a disabled button's tooltip never shows on a phone. -->
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            disabled={!aiAvailable || !!busy[c.id]}
            title={aiAvailable ? undefined : $t('review.ai_unavailable')}
            onclick={() => fillWithAi(c)}>✨ {$t('review.ai')}</button
          >
          <span class="spacer"></span>
          <button type="button" class="btn-link" onclick={() => dismiss(c)}>{$t('review.dismiss')}</button>
          <button type="button" class="btn-link" onclick={() => ignoreSender(c)}>{$t('review.ignore_sender')}</button>
        </footer>
      </article>
    {/each}
  {/if}
</div>

<style>
  .review-page {
    max-width: 820px;
  }
  .review-intro {
    color: var(--text-secondary);
    font-size: 0.9rem;
    margin: 0 0 var(--space-md);
  }
  .review-ai-hint {
    margin: -8px 0 var(--space-md);
  }
  .review-head {
    margin-bottom: 12px;
  }
  .review-subject {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 4px;
    overflow-wrap: anywhere;
  }
  .review-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    color: var(--text-secondary);
    font-size: 0.82rem;
  }
  .review-sender {
    overflow-wrap: anywhere;
  }
  .review-label {
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-bottom: 6px;
  }
  .chip-groups {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .chip-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .chip-group-label {
    font-size: 0.78rem;
    color: var(--text-secondary);
    min-width: 72px;
  }
  .chip {
    border: 1px solid var(--border-strong);
    background: var(--bg-subtle);
    color: var(--text-primary);
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 0.82rem;
    cursor: pointer;
    min-height: 32px;
  }
  .chip:hover {
    border-color: var(--accent);
  }
  .review-excerpt {
    margin: 12px 0;
  }
  .review-excerpt summary {
    cursor: pointer;
  }
  .excerpt-lines {
    border-left: 2px solid var(--border-strong);
    padding: 4px 0 4px 10px;
    font-size: 0.82rem;
    color: var(--text-secondary);
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .excerpt-line {
    overflow-wrap: anywhere;
  }
  .excerpt-line :global(mark) {
    background: color-mix(in srgb, var(--warning) 30%, transparent);
    color: var(--text-primary);
    border-radius: 3px;
    padding: 0 2px;
  }
  .review-note {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .review-form {
    margin-top: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .review-leg {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 10px 12px;
    margin: 0;
  }
  .review-leg legend {
    font-size: 0.8rem;
    color: var(--text-secondary);
    padding: 0 4px;
  }
  .airport-field {
    max-width: 120px;
  }
  .doubt {
    margin: 4px 0 0;
    font-size: 0.78rem;
    color: var(--warning-text);
  }
  .form-input.target {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .review-form-actions,
  .review-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .review-actions {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .spacer {
    flex: 1;
  }
  .btn-link {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 0.85rem;
    cursor: pointer;
    padding: 6px 4px;
    min-height: 36px;
  }
  .btn-link:hover {
    color: var(--text-primary);
    text-decoration: underline;
  }
  @media (max-width: 560px) {
    .airport-field {
      max-width: none;
    }
    .chip-group-label {
      min-width: 100%;
    }
  }
</style>
