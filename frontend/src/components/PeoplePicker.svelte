<script lang="ts">
  import type { Participant } from '../api/types';
  import { t } from '../lib/i18n';

  /**
   * Pick some of the people on a trip — who a bill is split between, who a
   * budget belongs to. One component for both, because two controls doing the
   * same job on the same page have drifted apart twice already.
   *
   * A **token combobox**, not an inline list. The list is bounded by the trip
   * (owner, accepted collaborators, guests already tagged on it) so it cannot
   * reach the size of the user table — but a group trip with twenty companions
   * is ordinary, and an inline list of everyone costs the form a fixed block of
   * height on every trip to serve the rare one. Here the resting size is what
   * you have *chosen*, usually one or two names, and the candidates appear only
   * while you are choosing.
   *
   * Two details are deliberate and easy to "fix" into bugs:
   *
   * 1. **Focus opens the full list**, so this is still browsable by someone who
   *    does not know who is on the trip. A pure type-to-search box hides the
   *    fact that there is anything to pick — the same reason `PlaceInput`
   *    reopens its results on focus.
   * 2. **Suggestions exclude what is already chosen.** A picked person is a
   *    token; leaving them in the list too offers one person in two places,
   *    which is the bug the payer select had.
   *
   * Unlike `PlaceInput` there is no debounce and no request sequencing: the
   * candidates are already in memory, so filtering is synchronous.
   */
  interface Props {
    people: Participant[];
    /** Selected `type:id` keys. Owned by the parent — this component reports
     *  toggles and never mutates. */
    selected: Set<string>;
    onToggle: (person: Participant) => void;
    label: string;
    hint?: string;
    /** How each person is named — the caller marks its own row "(you)". */
    display?: (person: Participant) => string;
    id?: string;
  }

  const {
    people,
    selected,
    onToggle,
    label,
    hint,
    display = (p: Participant) => p.name,
    id,
  }: Props = $props();

  let query = $state('');
  let open = $state(false);
  let highlighted = $state(-1);

  const key = (p: Participant) => `${p.type}:${p.id}`;

  /* Accent-folded so "joao" finds "João" — the names here are typed by hand in
   * a pt-BR app, and a filter that misses its own users' names is worse than no
   * filter. Mirrors `fold_text` on the backend. */
  const fold = (value: string) =>
    value
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase();

  const chosen = $derived(people.filter((p) => selected.has(key(p))));
  const suggestions = $derived.by(() => {
    const needle = fold(query.trim());
    return people.filter(
      (p) => !selected.has(key(p)) && (!needle || fold(p.name).includes(needle)),
    );
  });

  function pick(person: Participant) {
    onToggle(person);
    query = '';
    highlighted = -1;
    // Stays open: adding two people in a row is the common case, and a box
    // that closes after each pick makes the second one a fresh hunt.
    open = true;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      open = true;
      if (suggestions.length > 0) highlighted = (highlighted + 1) % suggestions.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (suggestions.length > 0) {
        highlighted = highlighted <= 0 ? suggestions.length - 1 : highlighted - 1;
      }
    } else if (e.key === 'Enter') {
      // Only when a row is actually highlighted — Enter on a bare query must
      // not submit the surrounding form by accident either.
      if (highlighted >= 0 && suggestions[highlighted]) {
        e.preventDefault();
        pick(suggestions[highlighted]);
      } else if (query.trim() && suggestions.length === 1) {
        e.preventDefault();
        pick(suggestions[0]);
      }
    } else if (e.key === 'Escape') {
      open = false;
      highlighted = -1;
    } else if (e.key === 'Backspace' && query === '' && chosen.length > 0) {
      // The standard token-field gesture: backspace on an empty box takes back
      // the last thing you added.
      onToggle(chosen[chosen.length - 1]);
    }
  }
</script>

<div class="people-picker">
  <span class="form-label">{label}</span>

  <!-- What you have chosen is the control's resting state, so it is the part
       that is always visible. -->
  {#if chosen.length > 0}
    <div class="people-tokens">
      {#each chosen as person (key(person))}
        <span class="people-token">
          {display(person)}
          <button
            type="button"
            class="people-token-remove"
            aria-label={$t('people.remove', { values: { name: person.name } })}
            onclick={() => onToggle(person)}
          >
            ×
          </button>
        </span>
      {/each}
    </div>
  {/if}

  <div class="people-combo">
    <input
      {id}
      class="form-input people-input"
      type="text"
      autocomplete="off"
      role="combobox"
      aria-expanded={open}
      aria-controls="people-suggestions"
      placeholder={chosen.length === 0
        ? $t('people.add_first_placeholder')
        : $t('people.add_placeholder')}
      bind:value={query}
      oninput={() => {
        open = true;
        highlighted = -1;
      }}
      onkeydown={onKeydown}
      onfocus={() => (open = true)}
      onblur={() => setTimeout(() => (open = false), 150)}
    />

    {#if open && suggestions.length > 0}
      <ul class="people-suggestions" id="people-suggestions">
        {#each suggestions as person, i (key(person))}
          <li>
            <button
              type="button"
              class="people-suggestion"
              class:highlighted={i === highlighted}
              onmousedown={(e) => {
                e.preventDefault();
                pick(person);
              }}
              onmouseenter={() => (highlighted = i)}
            >
              {display(person)}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    <!-- A box that matches nothing must say so; an empty dropdown reads as a
         list that failed to load. -->
    {#if open && suggestions.length === 0}
      <p class="people-empty">
        {people.length > 0 && chosen.length === people.length
          ? $t('people.all_added')
          : $t('people.no_matches')}
      </p>
    {/if}
  </div>

  {#if hint}
    <p class="people-hint">{hint}</p>
  {/if}
</div>

<style>
  .people-picker {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
    min-width: 0;
  }

  .people-tokens {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }

  /* A neutral pill. Not accent-filled: the accent is worn by four things in
     this design language and a list of companions is not one of them. */
  .people-token {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.8rem;
    padding: 2px 4px 2px var(--space-xs);
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-subtle, var(--bg-card));
  }

  .people-token-remove {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.1rem;
    height: 1.1rem;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: none;
    color: var(--text-muted);
    font-size: 0.95rem;
    line-height: 1;
    cursor: pointer;
  }

  .people-token-remove:hover {
    color: var(--danger-text, var(--danger));
  }

  .people-combo {
    position: relative;
  }

  .people-input {
    width: 100%;
  }

  /* An overlay, so a long list costs the form no height at all — which is the
     whole reason this is a combobox and not an inline list. Capped and
     scrolling for the trip that really does have twenty companions. */
  .people-suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 20;
    margin: 2px 0 0;
    padding: 0;
    list-style: none;
    max-height: 12rem;
    overflow-y: auto;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 4px);
    box-shadow: var(--shadow-md, 0 4px 12px rgb(0 0 0 / 0.15));
  }

  .people-suggestion {
    display: block;
    width: 100%;
    padding: var(--space-xs) var(--space-sm);
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    font-size: 0.85rem;
    text-align: left;
    cursor: pointer;
  }

  .people-suggestion.highlighted {
    background: var(--bg-subtle, var(--bg-hover));
  }

  .people-empty,
  .people-hint {
    margin: 0;
    font-size: 0.75rem;
    color: var(--text-muted);
  }
</style>
